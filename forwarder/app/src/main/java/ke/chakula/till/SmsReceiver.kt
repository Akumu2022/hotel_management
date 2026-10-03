package ke.chakula.till

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony

/**
 * Fires the moment an SMS arrives. M-Pesa messages are queued and an upload is started; all
 * other messages are ignored here and never stored or sent. Long messages arrive in parts, which
 * are joined first (the same text the inbox shows, so the rescan finds the same message ID).
 */
class SmsReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return
        val parts = Telephony.Sms.Intents.getMessagesFromIntent(intent) ?: return
        val bySender = parts.filterNotNull().groupBy { it.displayOriginatingAddress ?: it.originatingAddress ?: "" }
        val store = Store(context)
        val found = bySender.filterKeys { Store.isMpesa(it) }.map { (sender, msgs) ->
            val body = msgs.joinToString("") { it.displayMessageBody ?: it.messageBody ?: "" }
            val sentAt = msgs.first().timestampMillis
            Sms(Store.messageId(sender, sentAt, body), sender, body, sentAt)
        }
        if (found.isEmpty() || !store.paired) return
        store.enqueue(found)
        Sync.uploadSoon(context)
    }
}
