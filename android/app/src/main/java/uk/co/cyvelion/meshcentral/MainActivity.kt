// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral

import android.os.Bundle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import uk.co.cyvelion.meshcentral.ui.AccountScreen
import uk.co.cyvelion.meshcentral.ui.AppLockScreen
import uk.co.cyvelion.meshcentral.ui.ChatScreen
import uk.co.cyvelion.meshcentral.ui.ConnectionStatus
import uk.co.cyvelion.meshcentral.ui.ConsoleScreen
import uk.co.cyvelion.meshcentral.ui.DesktopScreen
import uk.co.cyvelion.meshcentral.ui.DeviceEventsScreen
import uk.co.cyvelion.meshcentral.ui.DeviceScreen
import uk.co.cyvelion.meshcentral.ui.DevicesScreen
import uk.co.cyvelion.meshcentral.ui.FilesScreen
import uk.co.cyvelion.meshcentral.ui.LoginScreen
import uk.co.cyvelion.meshcentral.ui.McdTheme
import uk.co.cyvelion.meshcentral.ui.MyFilesScreen
import uk.co.cyvelion.meshcentral.ui.NotesScreen
import uk.co.cyvelion.meshcentral.ui.ProcessesScreen
import uk.co.cyvelion.meshcentral.ui.RegistryScreen
import uk.co.cyvelion.meshcentral.ui.ServerEventsScreen
import uk.co.cyvelion.meshcentral.ui.ServerScreen
import uk.co.cyvelion.meshcentral.ui.ServicesScreen
import uk.co.cyvelion.meshcentral.ui.SettingsScreen
import uk.co.cyvelion.meshcentral.ui.SoftwareScreen
import uk.co.cyvelion.meshcentral.ui.TerminalScreen
import uk.co.cyvelion.meshcentral.ui.UserGroupsScreen
import uk.co.cyvelion.meshcentral.ui.UsersScreen

// FragmentActivity: the app lock's system prompt (BiometricPrompt) needs it
class MainActivity : androidx.fragment.app.FragmentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val app = McdApp.instance
        privacy()
        setContent {
            McdTheme {
                androidx.compose.foundation.layout.Box {
                val session = app.session
                if (session == null) {
                    LoginScreen(app)
                } else {
                    val nav = rememberNavController()
                    androidx.compose.foundation.layout.Box {
                    // short slide instead of the default slow cross-fade; the back gesture drags the page off to the
                    // right with the finger (predictive back seeks the pop transition)
                    val ease = androidx.compose.animation.core.FastOutSlowInEasing
                    val spec = androidx.compose.animation.core.tween<androidx.compose.ui.unit.IntOffset>(260, easing = ease)
                    val fade = androidx.compose.animation.core.tween<Float>(200, easing = ease)
                    NavHost(nav, startDestination = "devices",
                        enterTransition = { slideInHorizontally(spec) { it / 3 } + fadeIn(fade) },
                        exitTransition = { slideOutHorizontally(spec) { -it / 8 } + fadeOut(fade, targetAlpha = 0.6f) },
                        popEnterTransition = { slideInHorizontally(spec) { -it / 8 } + fadeIn(fade, initialAlpha = 0.6f) },
                        popExitTransition = { slideOutHorizontally(spec) { it } }) {
                        composable("devices") {
                            DevicesScreen(app, session, onOpen = { nav.navigate("device/" + android.net.Uri.encode(it)) },
                                onNav = { nav.navigate(it) })
                        }
                        composable("device/{id}") { entry ->
                            val id = entry.arguments?.getString("id") ?: ""
                            DeviceScreen(app, session, id, onBack = { nav.popBackStack() },
                                onOpen = { page -> nav.navigate("$page/" + android.net.Uri.encode(id)) })
                        }
                        composable("desktop/{id}") { entry ->
                            DesktopScreen(session, entry.arguments?.getString("id") ?: "", onBack = { nav.popBackStack() })
                        }
                        composable("chat/{id}") { entry ->
                            ChatScreen(session, entry.arguments?.getString("id") ?: "", onBack = { nav.popBackStack() })
                        }
                        composable("files/{id}") { entry ->
                            FilesScreen(session, entry.arguments?.getString("id") ?: "", onBack = { nav.popBackStack() })
                        }
                        composable("terminal/{id}") { entry ->
                            TerminalScreen(session, entry.arguments?.getString("id") ?: "", onBack = { nav.popBackStack() })
                        }
                        // device tools
                        val back = { nav.popBackStack(); Unit }
                        composable("events/{id}") { e -> DeviceEventsScreen(session, e.arguments?.getString("id") ?: "", back) }
                        composable("notes/{id}") { e -> NotesScreen(session, e.arguments?.getString("id") ?: "", back) }
                        composable("processes/{id}") { e -> ProcessesScreen(session, e.arguments?.getString("id") ?: "", back) }
                        composable("services/{id}") { e -> ServicesScreen(session, e.arguments?.getString("id") ?: "", back) }
                        composable("software/{id}") { e -> SoftwareScreen(session, e.arguments?.getString("id") ?: "", back) }
                        composable("console/{id}") { e -> ConsoleScreen(session, e.arguments?.getString("id") ?: "", back) }
                        composable("registry/{id}") { e -> RegistryScreen(session, e.arguments?.getString("id") ?: "", back) }
                        // site pages (drawer)
                        composable("myfiles") { MyFilesScreen(app, session, back) }
                        composable("events") { ServerEventsScreen(session, back) }
                        composable("users") { UsersScreen(app, session, back) }
                        composable("usergroups") { UserGroupsScreen(app, session, back) }
                        composable("server") { ServerScreen(app, session, back) }
                        composable("account") { AccountScreen(app, session, back) }
                        composable("settings") { SettingsScreen(app, back) }
                    }
                    ConnectionStatus(app, session)
                    }
                }
                AppLockScreen(this@MainActivity)
                }
            }
        }
    }

    /**
     * With the app lock on, the recent-apps screen shows no preview of the app: Android 13+ has a switch for that;
     * older versions only have FLAG_SECURE (which also blocks screenshots of the app while the lock is on).
     * Always: touches that pass through another app's see-through overlay are ignored (tapjacking on "Power off",
     * "Delete device"...); Android 12+ blocks most of those itself.
     */
    fun privacy() {
        val locking = uk.co.cyvelion.meshcentral.data.AppLock.enabled
        if (android.os.Build.VERSION.SDK_INT >= 33) setRecentsScreenshotEnabled(!locking)
        else if (locking) window.addFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE)
        else window.clearFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE)
        window.decorView.filterTouchesWhenObscured = true
    }
}