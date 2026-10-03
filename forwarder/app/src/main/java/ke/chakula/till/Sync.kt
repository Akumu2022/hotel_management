package ke.chakula.till

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.os.BatteryManager
import android.os.Build
import android.provider.Telephony
import androidx.core.content.ContextCompat
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Getting messages to the server reliably (DECISIONS D26), without a permanent notification:
 * - on every M-Pesa SMS, an upload job runs as soon as there is internet;
 * - every 15 minutes, a check-in job rescans the inbox for the last 3 days (catches anything
 *   missed while the phone was off, offline, or the app was killed), uploads, and reports health.
 * The server ignores repeats, so sending twice is always safe.
 */
object Sync {
    private val online = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()

    fun uploadSoon(context: Context) {
        val work = OneTimeWorkRequestBuilder<UploadWorker>()
            .setConstraints(online)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 15, TimeUnit.SECONDS)
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork("upload", ExistingWorkPolicy.APPEND_OR_REPLACE, work)
    }

    fun schedule(context: Context) {
        val work = PeriodicWorkRequestBuilder<CheckInWorker>(15, TimeUnit.MINUTES)
            .setConstraints(online)
            .build()
        WorkManager.getInstance(context).enqueueUniquePeriodicWork("check-in", ExistingPeriodicWorkPolicy.UPDATE, work)
    }

    fun checkInNow(context: Context) {
        WorkManager.getInstance(context).enqueueUniqueWork(
            "check-in-now",
            ExistingWorkPolicy.REPLACE,
            OneTimeWorkRequestBuilder<CheckInWorker>().setConstraints(online).build(),
        )
    }

    fun hasSmsPermission(context: Context) =
        ContextCompat.checkSelfPermission(context, Manifest.permission.RECEIVE_SMS) == PackageManager.PERMISSION_GRANTED &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.READ_SMS) == PackageManager.PERMISSION_GRANTED

    /** M-Pesa messages from the last [days] days that the server hasn't acknowledged. */
    fun rescanInbox(context: Context, store: Store, days: Int = 3): Int {
        if (!hasSmsPermission(context)) return 0
        val since = System.currentTimeMillis() - days * Store.DAY
        val found = mutableListOf<Sms>()
        context.contentResolver.query(
            Telephony.Sms.Inbox.CONTENT_URI,
            arrayOf(Telephony.Sms.ADDRESS, Telephony.Sms.BODY, Telephony.Sms.DATE_SENT, Telephony.Sms.DATE),
            "${Telephony.Sms.DATE} > ?",
            arrayOf(since.toString()),
            "${Telephony.Sms.DATE} ASC",
        )?.use { c ->
            while (c.moveToNext()) {
                val sender = c.getString(0) ?: continue
                if (!Store.isMpesa(sender)) continue
                val body = c.getString(1) ?: continue
                val sentAt = c.getLong(2).takeIf { it > 0 } ?: c.getLong(3)
                val id = Store.messageId(sender, sentAt, body)
                if (!store.isKnown(id)) found += Sms(id, sender, body, sentAt)
            }
        }
        return store.enqueue(found)
    }

    /** Uploads the whole queue in batches. Throws on network or server errors (job retries). */
    fun drain(store: Store, api: Api) {
        while (true) {
            val batch = store.queued(50)
            if (batch.isEmpty()) return
            val done = api.send(batch)
            store.acknowledge(done)
            store.lastSent = System.currentTimeMillis()
            store.lastContact = store.lastSent
            if (done.size < batch.size) return // the rest next time
        }
    }

    fun report(context: Context, store: Store): JSONObject {
        val battery = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val level = battery?.let { it.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) * 100 / it.getIntExtra(BatteryManager.EXTRA_SCALE, 100) }
        val plugged = (battery?.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) ?: 0) != 0
        return JSONObject()
            .put("app_version", BuildConfig.VERSION_NAME)
            .put("battery", level?.takeIf { it in 0..100 })
            .put("charging", plugged)
            .put("pending", store.pending)
            .put("sms_permission", hasSmsPermission(context))
            .put("android", Build.VERSION.RELEASE)
            .apply { store.lastError?.let { put("last_error", it.take(200)) } }
    }

    /** Problems the person at the till must fix get stored for the screen; others retry. */
    fun handle(store: Store, e: Exception): Boolean {
        store.lastError = e.message
        if (e is ApiError) {
            when (e.code) {
                "unpaired" -> { store.problem = "unpaired"; return false }
                "clock_skew" -> { store.problem = "clock"; return false }
                "bad_signature" -> { store.problem = "unpaired"; return false }
            }
        }
        return true // network trouble: try again later
    }
}

class UploadWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val store = Store(applicationContext)
        if (!store.paired) return Result.success()
        return try {
            Sync.drain(store, Api(store))
            store.problem = null
            store.lastError = null
            Result.success()
        } catch (e: Exception) {
            if (Sync.handle(store, e)) Result.retry() else Result.failure()
        }
    }
}

class CheckInWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val store = Store(applicationContext)
        if (!store.paired) return Result.success()
        val api = Api(store)
        return try {
            Sync.rescanInbox(applicationContext, store)
            Sync.drain(store, api)
            api.heartbeat(Sync.report(applicationContext, store))
            store.lastContact = System.currentTimeMillis()
            store.problem = null
            store.lastError = null
            Result.success()
        } catch (e: Exception) {
            if (Sync.handle(store, e)) Result.retry() else Result.failure()
        }
    }
}
