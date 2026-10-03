package ke.chakula.till

import android.content.Context
import android.content.SharedPreferences
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONObject
import java.security.KeyStore
import java.security.MessageDigest
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** One M-Pesa SMS waiting to reach the server. */
data class Sms(val id: String, val sender: String, val body: String, val receivedAt: Long)

/**
 * Everything the app remembers, in private app storage:
 * - pairing (server address, device ID, and the signing secret encrypted with a key that never
 *   leaves the phone's Android Keystore),
 * - the queue of messages not yet acknowledged by the server,
 * - the IDs the server already acknowledged (so the inbox rescan doesn't resend them), 7 days.
 */
class Store(context: Context) {
    private val prefs: SharedPreferences =
        context.applicationContext.getSharedPreferences("till", Context.MODE_PRIVATE)

    // --- Pairing ---------------------------------------------------------------------------

    val paired: Boolean get() = deviceId != null && secret() != null
    var server: String
        get() = prefs.getString("server", BuildConfig.DEFAULT_SERVER) ?: BuildConfig.DEFAULT_SERVER
        set(v) = prefs.edit().putString("server", v.trim().trimEnd('/')).apply()
    val deviceId: String? get() = prefs.getString("device_id", null)
    val hotelName: String? get() = prefs.getString("hotel_name", null)
    val tillNumber: String? get() = prefs.getString("till_number", null)

    fun savePairing(deviceId: String, secretHex: String, hotel: String, till: String) {
        prefs.edit()
            .putString("device_id", deviceId)
            .putString("secret", encrypt(hex(secretHex)))
            .putString("hotel_name", hotel)
            .putString("till_number", till)
            .remove("problem")
            .apply()
    }

    fun forget() {
        prefs.edit().remove("device_id").remove("secret").remove("hotel_name").remove("till_number").apply()
    }

    fun secret(): ByteArray? = prefs.getString("secret", null)?.let { runCatching { decrypt(it) }.getOrNull() }

    // --- Status shown on screen --------------------------------------------------------------

    var lastSent: Long
        get() = prefs.getLong("last_sent", 0)
        set(v) = prefs.edit().putLong("last_sent", v).apply()
    var lastContact: Long
        get() = prefs.getLong("last_contact", 0)
        set(v) = prefs.edit().putLong("last_contact", v).apply()
    /** A problem the person at the till must fix (unpaired, wrong clock), or null. */
    var problem: String?
        get() = prefs.getString("problem", null)
        set(v) = prefs.edit().putString("problem", v).apply()
    var lastError: String?
        get() = prefs.getString("last_error", null)
        set(v) = prefs.edit().putString("last_error", v).apply()

    // --- Queue -----------------------------------------------------------------------------

    @Synchronized
    fun enqueue(items: List<Sms>): Int {
        val q = JSONObject(prefs.getString("queue", "{}")!!)
        val acked = JSONObject(prefs.getString("acked", "{}")!!)
        var added = 0
        for (s in items) {
            if (q.has(s.id) || acked.has(s.id)) continue
            q.put(s.id, JSONObject().put("sender", s.sender).put("body", s.body).put("at", s.receivedAt))
            added++
        }
        if (added > 0) prefs.edit().putString("queue", q.toString()).commit()
        return added
    }

    @Synchronized
    fun queued(limit: Int = 50): List<Sms> {
        val q = JSONObject(prefs.getString("queue", "{}")!!)
        return q.keys().asSequence().map { id ->
            val o = q.getJSONObject(id)
            Sms(id, o.getString("sender"), o.getString("body"), o.getLong("at"))
        }.sortedBy { it.receivedAt }.take(limit).toList()
    }

    val pending: Int @Synchronized get() = JSONObject(prefs.getString("queue", "{}")!!).length()

    @Synchronized
    fun acknowledge(ids: Collection<String>) {
        val q = JSONObject(prefs.getString("queue", "{}")!!)
        val acked = JSONObject(prefs.getString("acked", "{}")!!)
        val now = System.currentTimeMillis()
        ids.forEach { q.remove(it); acked.put(it, now) }
        // Forget acknowledgements older than the rescan window plus a margin.
        val old = acked.keys().asSequence().filter { acked.getLong(it) < now - 7 * DAY }.toList()
        old.forEach { acked.remove(it) }
        prefs.edit().putString("queue", q.toString()).putString("acked", acked.toString()).commit()
    }

    fun isKnown(id: String): Boolean {
        val q = JSONObject(prefs.getString("queue", "{}")!!)
        return q.has(id) || JSONObject(prefs.getString("acked", "{}")!!).has(id)
    }

    // --- Keystore encryption of the secret --------------------------------------------------

    private fun key(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        gen.init(
            KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .build(),
        )
        return gen.generateKey()
    }

    private fun encrypt(plain: ByteArray): String {
        val c = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
        val out = c.iv + c.doFinal(plain)
        return Base64.encodeToString(out, Base64.NO_WRAP)
    }

    private fun decrypt(stored: String): ByteArray {
        val raw = Base64.decode(stored, Base64.NO_WRAP)
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, raw, 0, 12))
        return c.doFinal(raw, 12, raw.size - 12)
    }

    companion object {
        private const val ALIAS = "chakula_till_secret"
        const val DAY = 24 * 60 * 60 * 1000L

        fun hex(s: String): ByteArray = ByteArray(s.length / 2) { s.substring(it * 2, it * 2 + 2).toInt(16).toByte() }

        /**
         * A stable ID for a message, the same whether it came from the SMS broadcast or the inbox
         * rescan: sender + the network's send time + the text.
         */
        fun messageId(sender: String, sentAt: Long, body: String): String {
            val d = MessageDigest.getInstance("SHA-256").digest("$sender|$sentAt|$body".toByteArray())
            return d.joinToString("") { "%02x".format(it) }.take(32)
        }

        fun isMpesa(sender: String?): Boolean =
            sender != null && sender.uppercase().replace(Regex("[^A-Z-]"), "") in setOf("MPESA", "M-PESA")
    }
}
