package ke.chakula.till

import android.app.Application

class TillApp : Application() {
    override fun onCreate() {
        super.onCreate()
        // WorkManager keeps the 15-minute check-in across reboots and app updates.
        if (Store(this).paired) Sync.schedule(this)
    }
}
