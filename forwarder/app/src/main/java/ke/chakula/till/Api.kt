package ke.chakula.till

import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.security.SecureRandom
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

class ApiError(val status: Int, val code: String, message: String) : IOException(message)

/**
 * The server's forwarder API (backend/app/api/v1/forwarder.py). Every call after pairing is
 * signed: HMAC-SHA256(secret, "<timestamp>\n<nonce>\n<sha256 hex of body>").
 */
class Api(private val store: Store) {

    fun pair(server: String, code: String, label: String): JSONObject {
        val body = JSONObject()
            .put("code", code)
            .put("label", label)
            .put("app_version", BuildConfig.VERSION_NAME)
        return call("$server/api/v1/forwarder/pair", body.toString().toByteArray(), signed = false)
    }

    /** Sends queued messages; returns the IDs the server acknowledged. */
    fun send(messages: List<Sms>): List<String> {
        val arr = JSONArray()
        messages.forEach {
            arr.put(JSONObject().put("id", it.id).put("sender", it.sender).put("body", it.body).put("received_at", it.receivedAt))
        }
        val res = call(url("sms"), JSONObject().put("messages", arr).toString().toByteArray())
        val acc = res.getJSONArray("accepted")
        return List(acc.length()) { acc.getString(it) }
    }

    fun heartbeat(report: JSONObject): JSONObject = call(url("heartbeat"), report.toString().toByteArray())

    private fun url(path: String) = "${store.server}/api/v1/forwarder/$path"

    private fun call(url: String, body: ByteArray, signed: Boolean = true): JSONObject {
        val conn = URL(url).openConnection() as HttpURLConnection
        try {
            conn.requestMethod = "POST"
            conn.connectTimeout = 15_000
            conn.readTimeout = 20_000
            conn.doOutput = true
            conn.setRequestProperty("Content-Type", "application/json")
            conn.setRequestProperty("User-Agent", "ChakulaTill/${BuildConfig.VERSION_NAME}")
            if (signed) {
                val secret = store.secret() ?: throw ApiError(401, "unpaired", "Not paired")
                val ts = (System.currentTimeMillis() / 1000).toString()
                val nonce = randomHex(16)
                conn.setRequestProperty("X-Device-Id", store.deviceId)
                conn.setRequestProperty("X-Timestamp", ts)
                conn.setRequestProperty("X-Nonce", nonce)
                conn.setRequestProperty("X-Signature", sign(secret, ts, nonce, body))
            }
            conn.outputStream.use { it.write(body) }
            val status = conn.responseCode
            val text = (if (status < 400) conn.inputStream else conn.errorStream)?.bufferedReader()?.use { it.readText() } ?: ""
            if (status >= 400) {
                val err = runCatching { JSONObject(text).getJSONObject("error") }.getOrNull()
                throw ApiError(status, err?.optString("code") ?: "http_$status", err?.optString("message") ?: "Server error $status")
            }
            return if (text.isBlank()) JSONObject() else JSONObject(text)
        } finally {
            conn.disconnect()
        }
    }

    companion object {
        private val random = SecureRandom()

        fun randomHex(bytes: Int) = ByteArray(bytes).also { random.nextBytes(it) }.joinToString("") { "%02x".format(it) }

        fun sign(secret: ByteArray, ts: String, nonce: String, body: ByteArray): String {
            val bodyHash = MessageDigest.getInstance("SHA-256").digest(body).joinToString("") { "%02x".format(it) }
            val mac = Mac.getInstance("HmacSHA256").apply { init(SecretKeySpec(secret, "HmacSHA256")) }
            return mac.doFinal("$ts\n$nonce\n$bodyHash".toByteArray()).joinToString("") { "%02x".format(it) }
        }
    }
}
