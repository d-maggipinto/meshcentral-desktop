// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.combinedClickable
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material3.Button
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Devices
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.AccountCircle
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Dns
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.Groups
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.Person
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.NavigationDrawerItem
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.rememberCoroutineScope
import kotlinx.coroutines.launch
import uk.co.cyvelion.meshcentral.data.AppLock
import uk.co.cyvelion.meshcentral.data.Rights
import uk.co.cyvelion.meshcentral.data.Site
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.Switch
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import uk.co.cyvelion.meshcentral.McdApp
import uk.co.cyvelion.meshcentral.data.Node
import uk.co.cyvelion.meshcentral.data.Session

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DevicesScreen(app: McdApp, session: Session, onOpen: (String) -> Unit, onNav: (String) -> Unit) {
    val drawer = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    var addOpen by remember { mutableStateOf(false) }
    // long press a device: selection mode for group actions (device_list.GroupActions)
    var selected by remember { mutableStateOf(setOf<String>()) }
    var actionsOpen by remember { mutableStateOf(false) }
    androidx.activity.compose.BackHandler(selected.isNotEmpty()) { selected = emptySet() }
    androidx.activity.compose.BackHandler(drawer.isOpen) { scope.launch { drawer.close() } }
    var query by rememberSaveable { mutableStateOf("") }
    var onlineOnly by rememberSaveable { mutableStateOf(false) }
    var menu by remember { mutableStateOf(false) }
    // like the desktop app: sections start collapsed, the opened ones are remembered
    var expanded by remember { mutableStateOf(app.settings.getStringSet("expanded")) }
    // Android 13+: ask once for permission to show notifications (messages, device connections)
    val askNotify = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { }
    LaunchedEffect(Unit) {
        if (android.os.Build.VERSION.SDK_INT >= 33 && !app.settings.getBool("asked_notify", false)) {
            app.settings.putBool("asked_notify", true)
            askNotify.launch(android.Manifest.permission.POST_NOTIFICATIONS)
        }
    }
    val user = session.ctrl.username
    val host = session.ctrl.server.host

    val q = query.trim().lowercase()
    val shown = session.nodes.filter { n ->
        (!onlineOnly || n.online) && (q.isEmpty() || n.name.lowercase().contains(q) || n.host.lowercase().contains(q)
            || n.os.lowercase().contains(q) || n.tags.any { it.lowercase().contains(q) }
            || n.description.lowercase().contains(q))
    }
    val groups = shown.groupBy { it.meshId }.toList()
        .sortedBy { (id, _) -> (session.meshes[id]?.name ?: id).lowercase() }
    val allOpen = q.isNotEmpty() || onlineOnly || groups.size == 1

    val ui = session.ctrl.userinfo
    ModalNavigationDrawer(drawerState = drawer, drawerContent = {
        ModalDrawerSheet {
            Row(Modifier.padding(horizontal = 24.dp, vertical = 20.dp), verticalAlignment = Alignment.CenterVertically) {
                AdmAvatar(user, size = 48, image = UserImages.image(session, ui?.optString("_id") ?: "", UserImages.flags(ui)))
                Column(Modifier.padding(start = 12.dp)) {
                    Text(user, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold,
                        maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(host, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
            HorizontalDivider(Modifier.padding(bottom = 8.dp))
            // the desktop app's navigation rail (mainwindow.NAV): entries only with the site right
            @Composable fun entry(label: String, icon: androidx.compose.ui.graphics.vector.ImageVector, route: String?, show: Boolean = true) {
                if (show) NavigationDrawerItem({ Text(label) }, route == null, {
                    scope.launch { drawer.close() }
                    if (route != null) onNav(route)
                }, Modifier.padding(horizontal = 12.dp), icon = { Icon(icon, null) })
            }
            entry("Devices", Icons.Filled.Devices, null)
            entry("Files", Icons.Filled.Folder, "myfiles", Site.has(ui, Site.FILEACCESS))
            entry("Server events", Icons.Filled.History, "events")
            entry("Users", Icons.Filled.Person, "users", Site.has(ui, Site.MANAGEUSERS))
            entry("User groups", Icons.Filled.Groups, "usergroups", Site.has(ui, Site.USERGROUPS))
            entry("Server", Icons.Filled.Dns, "server", Site.has(ui, Site.BACKUP or Site.RESTORE or Site.UPDATE))
            entry("Account", Icons.Filled.AccountCircle, "account")
            HorizontalDivider(Modifier.padding(vertical = 8.dp))
            NavigationDrawerItem({ Text("Settings") }, false, { scope.launch { drawer.close() }; onNav("settings") },
                Modifier.padding(horizontal = 12.dp), icon = { Icon(Icons.Filled.Settings, null) })
            NavigationDrawerItem({ Text("Sign out") }, false, { scope.launch { drawer.close() }; app.signOut() },
                Modifier.padding(horizontal = 12.dp), icon = { Icon(Icons.AutoMirrored.Filled.Logout, null) })
        }
    }) {
    Scaffold(floatingActionButton = {
        // like the web UI's "Add Agent": only with "manage devices" (4) on some device group
        val canAdd = session.meshes.values.any { m ->
            Rights.mesh(session.ctrl.serverinfo, ui, m.json).let { it == Rights.FULL || it and 4L != 0L }
        }
        if (canAdd && selected.isEmpty())
            ExtendedFloatingActionButton(onClick = { addOpen = true },
                modifier = Modifier.semantics { contentDescription = "Add device" }, icon = { Icon(Icons.Filled.Add, null) }, text = { Text("Add device") })
    }, topBar = {
        if (selected.isNotEmpty()) TopAppBar(
            title = { Text("${selected.size} selected") },
            navigationIcon = { IconButton({ selected = emptySet() }) { Icon(Icons.Filled.Close, "Clear selection") } },
            actions = {
                TextButton({ selected = session.nodes.map { it.id }.toSet() }) { Text("All") }
                Button({ actionsOpen = true }, Modifier.padding(end = 8.dp)) { Text("Actions") }
            },
            colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.primaryContainer))
        else TopAppBar(
            navigationIcon = { IconButton({ scope.launch { drawer.open() } }) { Icon(Icons.Filled.Menu, "Menu") } },
            title = {
                Column {
                    Text("Devices")
                    Text("$user @ $host", style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            },
            actions = {
                IconButton({ session.load() }) { Icon(Icons.Filled.Refresh, "Refresh") }
                Box {
                    IconButton({ menu = true }) { Icon(Icons.Filled.MoreVert, "More") }
                    DropdownMenu(menu, { menu = false }) {
                        DropdownMenuItem({ Text("Settings") }, onClick = { menu = false; onNav("settings") },
                            leadingIcon = { Icon(Icons.Filled.Settings, null) })
                        DropdownMenuItem({ Text("Sign out") }, onClick = { menu = false; app.signOut() },
                            leadingIcon = { Icon(Icons.AutoMirrored.Filled.Logout, null) })
                    }
                }
            })
    }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad)) {
            TextField(query, { query = it }, Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp), singleLine = true,
                placeholder = { Text("Search devices") }, shape = CircleShape,
                leadingIcon = { Icon(Icons.Filled.Search, null) },
                trailingIcon = { if (query.isNotEmpty()) IconButton({ query = "" }) { Icon(Icons.Filled.Close, "Clear") } },
                colors = TextFieldDefaults.colors(focusedIndicatorColor = Color.Transparent, unfocusedIndicatorColor = Color.Transparent,
                    focusedContainerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
                    unfocusedContainerColor = MaterialTheme.colorScheme.surfaceContainerHigh))
            val total = session.nodes.size
            val onlineCount = session.nodes.count { it.online }
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(!onlineOnly, { onlineOnly = false }, { Text("All  $total") })
                FilterChip(onlineOnly, { onlineOnly = true }, { Text("Online  $onlineCount") },
                    leadingIcon = { Box(Modifier.size(8.dp).background(OnlineGreen, CircleShape)) })
            }
            PullToRefreshBox(isRefreshing = !session.loaded, onRefresh = { session.load() },
                modifier = Modifier.fillMaxSize()) {
                LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 96.dp)) {
                    if (session.loaded && groups.isEmpty()) {
                        item {
                            Column(Modifier.fillMaxWidth().padding(top = 64.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                                Icon(Icons.Filled.Devices, null, Modifier.size(56.dp), tint = MaterialTheme.colorScheme.outline)
                                Text(if (session.nodes.isEmpty()) "No devices yet" else "No device matches",
                                    Modifier.padding(top = 12.dp), style = MaterialTheme.typography.titleMedium)
                                Text(if (session.nodes.isEmpty()) "Devices you can manage on this server appear here."
                                    else "Try another search or show all devices.", color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    style = MaterialTheme.typography.bodyMedium)
                            }
                        }
                    }
                    groups.forEach { (meshId, list) ->
                        val open = allOpen || meshId in expanded
                        item(key = "g:$meshId") {
                            val name = session.meshes[meshId]?.name ?: "Group"
                            val online = list.count { it.online }
                            Row(Modifier.fillMaxWidth().clickable(enabled = !allOpen) {
                                expanded = if (meshId in expanded) expanded - meshId else expanded + meshId
                                app.settings.putStringSet("expanded", expanded)
                            }.padding(start = 20.dp, end = 12.dp, top = 14.dp, bottom = 6.dp),
                                verticalAlignment = Alignment.CenterVertically) {
                                Text(name.uppercase(), Modifier.weight(1f), style = MaterialTheme.typography.labelLarge,
                                    fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.primary,
                                    maxLines = 1, overflow = TextOverflow.Ellipsis)
                                Text("$online of ${list.size} online", style = MaterialTheme.typography.labelMedium,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                                if (!allOpen) Icon(if (open) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore, null,
                                    Modifier.padding(start = 6.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                        }
                        if (open) {
                            val sorted = list.sortedWith(compareBy<Node>({ !it.online }, { it.name.lowercase() }))
                            items(sorted, key = { it.id }) { n ->
                                DeviceRow(n, session.meshes[n.meshId]?.name, n.id in selected,
                                    onLongClick = { selected = selected + n.id }) {
                                    if (selected.isEmpty()) onOpen(n.id)
                                    else selected = if (n.id in selected) selected - n.id else selected + n.id
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    }
    if (addOpen) AddDeviceSheet(app, session, null) { addOpen = false }
    if (actionsOpen) GroupActionsSheet(session, session.nodes.filter { it.id in selected },
        onDismiss = { actionsOpen = false }, onDone = { actionsOpen = false; selected = emptySet() })
}

@Composable
@OptIn(androidx.compose.foundation.ExperimentalFoundationApi::class)
fun DeviceRow(n: Node, group: String?, selected: Boolean = false, onLongClick: (() -> Unit)? = null, onClick: () -> Unit) {
    Surface(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp), shape = MaterialTheme.shapes.large,
        color = if (selected) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceContainerLow,
        border = BorderStroke(if (selected) 2.dp else 1.dp,
            if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f))) {
        Row(Modifier.combinedClickable(onLongClick = onLongClick, onClick = onClick).padding(horizontal = 12.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically) {
            OsAvatar(n)
            Column(Modifier.weight(1f).padding(start = 12.dp)) {
                Text(n.name, style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                val sub = n.os.ifEmpty { n.host }.ifEmpty { group ?: "" }
                if (sub.isNotEmpty()) Text(sub, style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                if (n.tags.isNotEmpty()) Text(n.tags.joinToString("  ·  "), style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.tertiary, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            if (selected) Icon(Icons.Filled.CheckCircle, "Selected", tint = MaterialTheme.colorScheme.primary)
            else Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, tint = MaterialTheme.colorScheme.outline)
        }
    }
}
