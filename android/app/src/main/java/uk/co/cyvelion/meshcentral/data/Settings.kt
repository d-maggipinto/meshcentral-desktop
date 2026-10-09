// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.data

import android.content.Context
import android.content.SharedPreferences
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** App settings (server, user name, remember) in private SharedPreferences. */
class Settings(context: Context) {
    private val prefs: SharedPreferences = context.getSharedPreferences("settings", Context.MODE_PRIVATE)

    var server: String
        get() = prefs.getString("server", "") ?: ""
        set(v) = prefs.edit().putString("server", v).apply()
    var username: String
        get() = prefs.getString("username", "") ?: ""
        set(v) = prefs.edit().putString("username", v).apply()
    var remember: Boolean
        get() = prefs.getBoolean("remember", false)
        set(v) = prefs.edit().putBoolean("remember", v).apply()

    fun getString(key: String): String = prefs.getString(key, "") ?: ""
    fun putString(key: String, v: String) = prefs.edit().putString(key, v).apply()
    fun getStringSet(key: String): Set<String> = prefs.getStringSet(key, emptySet()) ?: emptySet()
    fun putStringSet(key: String, v: Set<String>) = prefs.edit().putStringSet(key, v).apply()
    fun getBool(key: String, def: Boolean) = prefs.getBoolean(key, def)
    fun putBool(key: String, v: Boolean) = prefs.edit().putBoolean(key, v).apply()
}

/**
 * The saved password, encrypted with an AES-GCM key in the Android Keystore (the key never leaves the
 * device's secure hardware / keystore; the ciphertext is in private storage and excluded from backups).
 * Like the desktop app's keyring entry: one password per server + user name.
 */
class CredentialStore(context: Context) {
    private val prefs = context.getSharedPreferences("credentials", Context.MODE_PRIVATE)
    private val alias = "mcd-password-key"

    private fun key(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getEntry(alias, null) as? KeyStore.SecretKeyEntry)?.let { return it.secretKey }
        val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        gen.init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256)
            .build())
        return gen.generateKey()
    }

    private fun id(server: String, user: String) = "pw:" + server.trim().lowercase() + "\n" + user.trim()

    fun store(server: String, user: String, password: String) {
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.ENCRYPT_MODE, key())
        val enc = c.doFinal(password.toByteArray(Charsets.UTF_8))
        val blob = Base64.encodeToString(c.iv, Base64.NO_WRAP) + ":" + Base64.encodeToString(enc, Base64.NO_WRAP)
        prefs.edit().putString(id(server, user), blob).apply()
    }

    fun load(server: String, user: String): String? {
        val blob = prefs.getString(id(server, user), null) ?: return null
        return try {
            val (iv, enc) = blob.split(":").map { Base64.decode(it, Base64.NO_WRAP) }
            val c = Cipher.getInstance("AES/GCM/NoPadding")
            c.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, iv))
            String(c.doFinal(enc), Charsets.UTF_8)
        } catch (e: Exception) {
            null                                   // key lost (device reset of the keystore): ask again
        }
    }

    fun clear(server: String, user: String) = prefs.edit().remove(id(server, user)).apply()
}
