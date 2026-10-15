package ke.chakula.till

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/**
 * After the phone restarts (flat battery, power cut) or the app is updated: set the 15-minute
 * check-in up again and run one straight away, so messages that arrived while the phone was off
 * are uploaded without anyone opening the app.
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED && intent.action != Intent.ACTION_MY_PACKAGE_REPLACED) return
        if (!Store(context).paired) return
        Sync.schedule(context)
        Sync.checkInNow(context)
    }
}
