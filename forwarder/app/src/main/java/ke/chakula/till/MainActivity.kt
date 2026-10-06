package ke.chakula.till

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.text.format.DateUtils
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import kotlin.concurrent.thread

/**
 * One screen: pair the phone (server address + the 8-letter code from Chakula Settings), then a
 * setup checklist and live status. Staff should never need to open it again once all is green.
 */
class MainActivity : Activity() {
    private lateinit var store: Store
    private val ui = Handler(Looper.getMainLooper())
    private val tick = object : Runnable {
        override fun run() { render(); ui.postDelayed(this, 5_000) }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        store = Store(this)

        find<EditText>(R.id.server).setText(store.server)
        find<EditText>(R.id.label).setText(Build.MODEL ?: "Till phone")
        find<Button>(R.id.pair).setOnClickListener { pair() }
        find<Button>(R.id.smsButton).setOnClickListener { askSms() }
        find<Button>(R.id.batteryButton).setOnClickListener { askBattery() }
        find<Button>(R.id.checkNow).setOnClickListener {
            Sync.rescanInbox(this, store)
            Sync.checkInNow(this)
            toast(getString(R.string.checking))
        }
        find<Button>(R.id.unpair).setOnClickListener {
            store.forget()
            render()
        }
        find<Button>(R.id.appSettings).setOnClickListener { openAppSettings() }
    }

    override fun onResume() {
        super.onResume()
        ui.post(tick)
        if (store.paired && Sync.hasSmsPermission(this)) {
            Sync.schedule(this)
            Sync.checkInNow(this)
        }
    }

    override fun onPause() {
        super.onPause()
        ui.removeCallbacks(tick)
    }

    // --- Pairing -----------------------------------------------------------------------------

    private fun pair() {
        val server = find<EditText>(R.id.server).text.toString().trim().trimEnd('/')
        val code = find<EditText>(R.id.code).text.toString().uppercase().replace(Regex("[^A-Z0-9]"), "")
        val label = find<EditText>(R.id.label).text.toString().trim()
        if (!server.startsWith("http")) return showError(getString(R.string.err_server))
        if (code.length != 8) return showError(getString(R.string.err_code))
        val button = find<Button>(R.id.pair)
        button.isEnabled = false
        showError(null)
        thread {
            try {
                store.server = server
                val res = Api(store).pair(server, code, label)
                val skew = kotlin.math.abs(res.optLong("server_time") * 1000 - System.currentTimeMillis())
                store.savePairing(res.getString("device_id"), res.getString("secret"), res.getString("hotel_name"), res.getString("till_number"))
                ui.post {
                    button.isEnabled = true
                    find<EditText>(R.id.code).setText("")
                    if (skew > 4 * 60_000) showError(getString(R.string.err_clock))
                    if (Sync.hasSmsPermission(this)) {
                        Sync.schedule(this)
                        Sync.rescanInbox(this, store)
                        Sync.checkInNow(this)
                    } else askSms()
                    render()
                }
            } catch (e: ApiError) {
                ui.post { button.isEnabled = true; showError(e.message) }
            } catch (e: Exception) {
                val msg = e.message ?: ""
                val tls = e is javax.net.ssl.SSLException || msg.contains("TLS", true) || msg.contains("SSL", true)
                ui.post {
                    button.isEnabled = true
                    showError(if (tls && server.startsWith("https://")) getString(R.string.err_tls) else getString(R.string.err_network, msg))
                }
            }
        }
    }

    // --- Permissions ---------------------------------------------------------------------------

    private fun askSms() {
        requestPermissions(arrayOf(Manifest.permission.RECEIVE_SMS, Manifest.permission.READ_SMS), 1)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 1 && grantResults.isNotEmpty() && grantResults.all { it == PackageManager.PERMISSION_GRANTED }) {
            Sync.schedule(this)
            Sync.rescanInbox(this, store)
            Sync.checkInNow(this)
        }
        render()
    }

    @SuppressLint("BatteryLife")
    private fun askBattery() {
        startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
    }

    private fun openAppSettings() {
        startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
    }

    private fun batteryOk(): Boolean =
        (getSystemService(POWER_SERVICE) as PowerManager).isIgnoringBatteryOptimizations(packageName)

    // --- Screen --------------------------------------------------------------------------------

    private fun render() {
        val paired = store.paired
        find<View>(R.id.pairCard).visibility = if (paired) View.GONE else View.VISIBLE
        find<View>(R.id.statusCard).visibility = if (paired) View.VISIBLE else View.GONE
        find<View>(R.id.setupCard).visibility = if (paired) View.VISIBLE else View.GONE
        find<View>(R.id.unpair).visibility = if (paired) View.VISIBLE else View.GONE
        if (!paired) return

        val sms = Sync.hasSmsPermission(this)
        val battery = batteryOk()
        val contact = store.lastContact
        val fresh = contact > 0 && System.currentTimeMillis() - contact < 40 * 60_000
        val problem = store.problem
        val (dot, title) = when {
            problem == "unpaired" -> R.drawable.dot_bad to getString(R.string.status_unpaired)
            problem == "clock" -> R.drawable.dot_bad to getString(R.string.status_clock)
            !sms -> R.drawable.dot_bad to getString(R.string.status_no_sms)
            store.pending > 0 -> R.drawable.dot_warn to resources.getQuantityString(R.plurals.status_queued, store.pending, store.pending)
            !fresh -> R.drawable.dot_warn to getString(R.string.status_waiting)
            else -> R.drawable.dot_ok to getString(R.string.status_ok)
        }
        find<View>(R.id.statusDot).setBackgroundResource(dot)
        find<TextView>(R.id.statusTitle).text = title
        find<TextView>(R.id.hotel).text = getString(R.string.hotel_line, store.hotelName ?: "", store.tillNumber ?: "")
        find<TextView>(R.id.lastContact).text = getString(
            R.string.last_contact,
            if (contact > 0) DateUtils.getRelativeTimeSpanString(contact) else getString(R.string.never),
        )
        find<TextView>(R.id.lastSent).text = getString(
            R.string.last_sent,
            if (store.lastSent > 0) DateUtils.getRelativeTimeSpanString(store.lastSent) else getString(R.string.never),
        )
        find<TextView>(R.id.pending).text = getString(R.string.pending, store.pending)
        find<TextView>(R.id.lastError).apply {
            text = store.lastError?.let { getString(R.string.last_error, it) } ?: ""
            visibility = if (store.lastError != null && !fresh) View.VISIBLE else View.GONE
        }

        find<TextView>(R.id.smsState).text = getString(if (sms) R.string.done else R.string.todo)
        find<Button>(R.id.smsButton).visibility = if (sms) View.GONE else View.VISIBLE
        // Android 13+: an app installed from a file must be allowed "restricted settings" first.
        find<View>(R.id.restrictedHelp).visibility =
            if (!sms && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) View.VISIBLE else View.GONE
        find<TextView>(R.id.batteryState).text = getString(if (battery) R.string.done else R.string.todo)
        find<Button>(R.id.batteryButton).visibility = if (battery) View.GONE else View.VISIBLE
    }

    private fun showError(msg: String?) {
        find<TextView>(R.id.pairError).apply {
            text = msg ?: ""
            visibility = if (msg.isNullOrBlank()) View.GONE else View.VISIBLE
        }
    }

    private fun toast(msg: String) = android.widget.Toast.makeText(this, msg, android.widget.Toast.LENGTH_SHORT).show()

    private fun <T : View> find(id: Int): T = findViewById(id)
}
