package com.toad.companion.kiosk

import android.app.admin.DeviceAdminReceiver

/**
 * Makes Toad the phone's device owner (Android's "dedicated device" mode), which is what lets
 * it lock the phone to this one app. Set once over USB:
 *   adb shell dpm set-device-owner com.toad.companion/.kiosk.ToadAdmin
 * The phone must have no accounts signed in. Undo with the admin PIN (KioskPolicy.exit).
 */
class ToadAdmin : DeviceAdminReceiver()
