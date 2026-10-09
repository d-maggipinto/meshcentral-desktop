// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Campaign
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.GroupAdd
import androidx.compose.material.icons.filled.Groups
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import uk.co.cyvelion.meshcentral.McdApp
import uk.co.cyvelion.meshcentral.data.Rights
import uk.co.cyvelion.meshcentral.data.Session
import uk.co.cyvelion.meshcentral.data.Site
import uk.co.cyvelion.meshcentral.net.ControlConnection

/*
 * User groups (group_panel.py): the web UI's "My User Groups" list and "User Group - <name>" page.
 *   usergroups -> {ugroups:{id:{name, desc, links:{user/..:{name, rights}, mesh/..:{rights}, node/..:{rights}}, consent?, flags?, membershipType?}} | null}
 *   createusergroup {name, desc[, clone][, domain]} -> {result:'ok', ugrpid}   deleteusergroup {ugrpid} -> {result:'ok'}
 *   editusergroup {ugrpid, name?, desc?, consent?, flags?} (no reply; event usergroupchange)
 *   addusertousergroup {ugrpid, usernames:[short ids]} -> {result:'ok', added, failed}   removeuserfromusergroup {ugrpid, userid}
 *   addmeshuser / removemeshuser / adddeviceuser with the group id as user id
 * Changes need site right 256; groups synced from an identity provider (membershipType) keep name and members.
 */

private fun counts(g: JSONObject): Triple<Int, Int, Int> {
    val keys = admLinks(g).keys().asSequence().toList()
    return Triple(keys.count { it.startsWith("user/") }, keys.count { it.startsWith("mesh/") }, keys.count { it.startsWith("node/") })
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun UserGroupsScreen(app: McdApp, session: Session, onBack: () -> Unit) {
    val ctrl = session.ctrl
    val scope = rememberCoroutineScope()
    val can = Site.has(ctrl.userinfo, Site.USERGROUPS)
    var groups by remember { mutableStateOf<JSONObject?>(null) }
    var users by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
    var query by rememberSaveable { mutableStateOf("") }
    var openId by rememberSaveable { mutableStateOf<String?>(null) }
    var newGroup by remember { mutableStateOf<String?>(null) }      // "new" or "copy"
    var alert by remember { mutableStateOf<Pair<String, String>?>(null) }
    var soon by remember { mutableStateOf<Job?>(null) }

    fun request() {
        ctrl.send("action" to "usergroups")
        if (Site.has(ctrl.userinfo, Site.MANAGEUSERS)) ctrl.send("action" to "users")
    }
    fun refreshSoon(ms: Long = 1000) { soon?.cancel(); soon = scope.launch { delay(ms); request() } }

    DisposableEffect(Unit) {
        val onGroups: (JSONObject) -> Unit = { m -> groups = m.optJSONObject("ugroups") ?: JSONObject() }
        val onUsers: (JSONObject) -> Unit = { m ->
            m.optJSONArray("users")?.let { a -> users = (0 until a.length()).mapNotNull { a.optJSONObject(it) } }
        }
        val onEvent: (JSONObject) -> Unit = { m ->
            when (m.optJSONObject("event")?.optString("action")) {
                "createusergroup", "deleteusergroup", "usergroupchange", "meshchange", "createmesh", "deletemesh",
                "changenode", "removenode", "accountcreate", "accountremove" -> refreshSoon()
            }
        }
        ctrl.on("usergroups", onGroups); ctrl.on("users", onUsers); ctrl.on("event", onEvent)
        request()
        onDispose { ctrl.off("usergroups", onGroups); ctrl.off("users", onUsers); ctrl.off("event", onEvent); soon?.cancel() }
    }

    val open = openId?.let { groups?.optJSONObject(it)?.put("_id", it) }
    LaunchedEffect(open, groups) { if (openId != null && groups != null && open == null) openId = null }   // deleted
    BackHandler(enabled = openId != null) { openId = null }

    if (open != null) {
        GroupPage(session, open, users, onBack = { openId = null }, refreshSoon = { refreshSoon(700) },
            onAlert = { t, m -> alert = t to m })
    } else Scaffold(topBar = {
        TopAppBar(title = { Text("User groups") },
            navigationIcon = { IconButton(onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
            actions = {
                if (can && (groups?.length() ?: 0) > 0) IconButton({ newGroup = "copy" }) { Icon(Icons.Filled.ContentCopy, "Duplicate a group") }
                IconButton({ request() }) { Icon(Icons.Filled.Refresh, "Refresh") }
            })
    }, floatingActionButton = {
        if (can) ExtendedFloatingActionButton(onClick = { newGroup = "new" }, icon = { Icon(Icons.Filled.GroupAdd, null) }, text = { Text("New group") })
    }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad)) {
            AdmSearch(query, "Search groups") { query = it }
            val g = groups
            if (g == null) Box(Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
            else {
                val cross = ctrl.serverinfo.has("crossDomain")
                val q = query.trim().lowercase()
                val ids = g.keys().asSequence().filter { id ->
                    val o = g.optJSONObject(id) ?: return@filter false
                    q.isEmpty() || o.optString("name").lowercase().contains(q) || o.optString("desc").lowercase().contains(q)
                }.sortedBy { g.optJSONObject(it)?.optString("name")?.lowercase() }.toList()
                LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(top = 4.dp, bottom = 96.dp)) {
                    if (ids.isEmpty()) item {
                        Column(Modifier.fillMaxWidth().padding(top = 48.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                            Icon(Icons.Filled.Groups, null, Modifier.padding(8.dp), tint = MaterialTheme.colorScheme.outline)
                            Text(if (g.length() == 0) "No user groups" else "No group matches", style = MaterialTheme.typography.titleMedium)
                            if (g.length() == 0 && can) Text("Create one to give several users the same permissions.",
                                color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodyMedium)
                        }
                    }
                    items(ids, key = { it }) { id ->
                        val o = g.optJSONObject(id) ?: JSONObject()
                        var name = o.optString("name")
                        if (cross && admDomain(id).isNotEmpty()) name += ", ${admDomain(id)}"
                        GroupRow(name, o) { openId = id }
                    }
                }
            }
        }
    }
    newGroup?.let { kind ->
        GroupFormDialog(if (kind == "copy") "Duplicate user group" else "New user group",
            groups = if (kind == "copy") groups else null,
            domains = if (kind == "new") ctrl.serverinfo.optJSONArray("crossDomain")?.let { a -> (0 until a.length()).map { a.optString(it) } } else null,
            onClose = { newGroup = null }) { name, desc, clone, domain ->
            newGroup = null
            val m = JSONObject().put("action", "createusergroup").put("name", name).put("desc", desc)
            if (clone != null) m.put("clone", clone)
            if (domain != null) m.put("domain", domain)
            ctrl.send(m) { r ->
                if (r.optString("result") != "ok") alert = "Creating the user group failed" to r.optString("result")
                refreshSoon(300)
            }
        }
    }
    alert?.let { (t, m) -> AdmMessage(t, m) { alert = null } }
}

@Composable
private fun GroupRow(name: String, g: JSONObject, onClick: () -> Unit) {
    val (u, m, n) = counts(g)
    Surface(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp), shape = MaterialTheme.shapes.large,
        color = MaterialTheme.colorScheme.surfaceContainerLow,
        border = androidx.compose.foundation.BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f))) {
        Row(Modifier.clickable(onClick = onClick).padding(horizontal = 12.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            AdmAvatar(name)
            Column(Modifier.weight(1f).padding(start = 12.dp)) {
                Text(name, style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                if (g.optString("desc").isNotEmpty()) Text(g.optString("desc"), style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text("${if (u == 1) "1 user" else "$u users"}  ·  ${if (m == 1) "1 device group" else "$m device groups"}  ·  " +
                    if (n == 1) "1 device" else "$n devices", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.tertiary)
            }
            Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, tint = MaterialTheme.colorScheme.outline)
        }
    }
}

/** New / duplicate / edit form: name, description (+ source group, domain). */
@Composable
private fun GroupFormDialog(title: String, groups: JSONObject? = null, domains: List<String>? = null, name: String = "", desc: String = "",
                            nameReadOnly: Boolean = false, onClose: () -> Unit, onOk: (String, String, String?, String?) -> Unit) {
    var n by remember { mutableStateOf(name) }
    var d by remember { mutableStateOf(desc) }
    val srcs = groups?.keys()?.asSequence()?.sortedBy { groups.optJSONObject(it)?.optString("name")?.lowercase() }
        ?.map { it to (groups.optJSONObject(it)?.optString("name") ?: it) }?.toList()
    var src by remember { mutableStateOf(srcs?.firstOrNull()?.first) }
    var dom by remember { mutableStateOf(domains?.firstOrNull()) }
    AdmFormDialog(title, okEnabled = n.isNotBlank(), onDismiss = onClose, onOk = { onOk(n.trim(), d.take(1024), src, dom) }) {
        if (srcs != null) AdmPicker("Copy of", srcs, src) { src = it }
        if (domains != null) AdmPicker("Domain", domains.map { it to it.ifEmpty { "Default" } }, dom) { dom = it }
        OutlinedTextField(n, { n = it.take(64) }, Modifier.fillMaxWidth(), label = { Text("Name") }, singleLine = true, enabled = !nameReadOnly)
        OutlinedTextField(d, { d = it.take(1024) }, Modifier.fillMaxWidth().padding(top = 4.dp), label = { Text("Description") }, minLines = 3)
        if (srcs != null) Text("The copy gets the same members and device group permissions (the server does not copy per-device permissions).",
            Modifier.padding(top = 6.dp), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun GroupPage(session: Session, g: JSONObject, users: List<JSONObject>, onBack: () -> Unit,
                      refreshSoon: () -> Unit, onAlert: (String, String) -> Unit) {
    val ctrl = session.ctrl
    val si = ctrl.serverinfo
    val gid = g.optString("_id")
    val name = g.optString("name")
    val synced = g.has("membershipType")
    val sa = admSiteRights(ctrl)
    val can = Site.has(ctrl.userinfo, Site.USERGROUPS)
    val links = admLinks(g)
    val guest = admGuest(ctrl)
    val (nUsers, nMeshes, nNodes) = counts(g)
    var dialog by remember { mutableStateOf<String?>(null) }
    var editMesh by remember { mutableStateOf<String?>(null) }
    var editNode by remember { mutableStateOf<String?>(null) }
    var confirm by remember { mutableStateOf<Triple<String, String, () -> Unit>?>(null) }

    fun reply(what: String): (JSONObject) -> Unit = { m ->
        if (!admReplyOk(m)) onAlert("$what failed", m.optString("result"))
        refreshSoon()
    }
    fun edit(vararg fields: Pair<String, Any?>) {
        val m = JSONObject().put("action", "editusergroup").put("ugrpid", gid)
        fields.forEach { (k, v) -> m.put(k, v) }
        ctrl.send(m)                                      // no reply: the usergroupchange event refreshes
        refreshSoon()
    }

    Scaffold(topBar = {
        TopAppBar(title = { Text(name, maxLines = 1, overflow = TextOverflow.Ellipsis) },
            navigationIcon = { IconButton(onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } })
    }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(bottom = 32.dp)) {
            Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                AdmAvatar(name, size = 60)
                Column(Modifier.weight(1f).padding(start = 16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(name, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    Text("User group" + if (synced) " (synced)" else "", style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            if (can) Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Box(Modifier.weight(1f)) {
                    ActionTile("Broadcast", Icons.Filled.Campaign, sa and 2L != 0L && nUsers > 0, Modifier.fillMaxWidth()) { dialog = "broadcast" }
                }
                Box(Modifier.weight(1f)) {
                    ActionTile("Add users", Icons.Filled.GroupAdd, !synced, Modifier.fillMaxWidth()) { dialog = "addusers" }
                }
            }
            SectionCard(title = "Details") {
                val dom = admDomain(gid)
                AdmInfoLine("Name", name, onEdit = if (can && !synced) ({ dialog = "edit" }) else null)
                AdmInfoLine("Domain", dom.ifEmpty { "Default" }, italic = dom.isEmpty())
                AdmInfoLine("Group ID", gid)
                if (synced) AdmInfoLine("Group type", g.opt("membershipType").toString())
                AdmInfoLine("Description", g.optString("desc").ifEmpty { "None" }, g.optString("desc").isEmpty(),
                    onEdit = if (can) ({ dialog = "edit" }) else null)
                if (si.optInt("userGroupsSessionRecording") == 1) {
                    val rec = g.optLong("flags") and 2L != 0L
                    AdmInfoLine("Features", if (rec) "Record Sessions" else "None", !rec, onEdit = if (can) ({ dialog = "features" }) else null)
                }
                val ct = admConsentText(g, si)
                AdmInfoLine("User consent", ct, ct == "None", onEdit = if (can) ({ dialog = "consent" }) else null)
                AdmInfoLine("Users", "$nUsers")
                AdmInfoLine("Device groups", "$nMeshes")
                AdmInfoLine("Devices", "$nNodes", last = true)
            }

            val me = ctrl.userinfo ?: JSONObject()
            val members = links.keys().asSequence().filter { it.startsWith("user/") }.map { uid ->
                var n = links.optJSONObject(uid)?.optString("name").orEmpty().ifEmpty { admShortId(uid) }
                if (uid == me.optString("_id")) n = me.optString("name").ifEmpty { n }
                n to uid
            }.sortedBy { it.first.lowercase() }.toList()
            AdmListSection("Members", "Add", if (!synced && can) ({ dialog = "addusers" }) else null,
                members.map { (n, uid) ->
                    AdmRow(n, users.firstOrNull { it.optString("_id") == uid }?.optString("email").orEmpty(),
                        onRemove = if (!synced && can) ({
                            confirm = Triple("Remove member", "Remove $n from the user group $name?") {
                                ctrl.send(JSONObject().put("action", "removeuserfromusergroup").put("ugrpid", gid).put("userid", uid),
                                    reply("Removing the member"))
                            }
                        }) else null)
                }, "No members")
            val meshes = session.meshes
            AdmListSection("Device groups", "Add",
                if (meshes.keys.any { admDomain(it) == admDomain(gid) && !links.has(it) }) ({ editMesh = "" }) else null,
                links.keys().asSequence().filter { it.startsWith("mesh/") && meshes.containsKey(it) }
                    .sortedBy { meshes[it]?.name?.lowercase() }.map { mid ->
                        val ok = Rights.mesh(si, ctrl.userinfo, meshes[mid]?.json) and 2L != 0L
                        AdmRow(meshes[mid]?.name ?: mid, admGroupRightsText(admLinkRights(links, mid), guest),
                            onEdit = if (ok) ({ editMesh = mid }) else null,
                            onRemove = if (ok) ({
                                confirm = Triple("Remove device group permissions", "Remove the access rights of $name to \"${meshes[mid]?.name}\"?") {
                                    ctrl.send(JSONObject().put("action", "removemeshuser").put("meshid", mid).put("userid", gid),
                                        reply("Removing the device group permissions"))
                                }
                            }) else null)
                    }.toList(), "No device groups in common")
            val same = admDomain(gid) == admDomain(me.optString("_id"))
            AdmListSection("Devices", "Add", if (same) ({ editNode = "" }) else null,
                links.keys().asSequence().filter { it.startsWith("node/") && session.node(it) != null }
                    .sortedBy { session.node(it)?.name?.lowercase() }.map { nid ->
                        val n = session.node(nid)!!
                        val ok = Rights.node(si, ctrl.userinfo, meshes[n.meshId]?.json, n.json) and 2L != 0L
                        AdmRow(n.name, admDeviceRightsText(admLinkRights(links, nid), guest),
                            onEdit = if (ok) ({ editNode = nid }) else null,
                            onRemove = if (ok) ({
                                confirm = Triple("Remove device permissions", "Remove the access rights of $name to \"${n.name}\"?") {
                                    ctrl.send(JSONObject().put("action", "adddeviceuser").put("nodeid", nid).put("nodename", n.name)
                                        .put("userids", JSONArray().put(gid)).put("rights", 0).put("remove", true),
                                        reply("Removing the device permissions"))
                                }
                            }) else null)
                    }.toList(), "No devices in common")

            if (can && (!synced || nUsers == 0)) Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp)) {
                Spacer(Modifier.weight(1f))
                OutlinedButton({
                    confirm = Triple("Delete user group", "Delete the user group $name? Its members keep their accounts.") {
                        ctrl.send(JSONObject().put("action", "deleteusergroup").put("ugrpid", gid)) { m ->
                            if (!admReplyOk(m)) onAlert("Deleting the user group failed", m.optString("result")) else onBack()
                            refreshSoon()
                        }
                    }
                }) { Text("Delete group", color = MaterialTheme.colorScheme.error) }
            }
        }
    }

    when (dialog) {
        "broadcast" -> AdmBroadcastDialog(ctrl, gid, name) { dialog = null }
        "edit" -> GroupFormDialog("Edit user group", name = name, desc = g.optString("desc"), nameReadOnly = synced,
            onClose = { dialog = null }) { n, d, _, _ -> dialog = null; edit("name" to n, "desc" to d) }
        "features" -> {
            var rec by remember { mutableStateOf(g.optLong("flags") and 2L != 0L) }
            AdmFormDialog("User group features", onDismiss = { dialog = null }, onOk = { dialog = null; edit("flags" to if (rec) 2 else 0) }) {
                AdmCheck("Record sessions", rec) { rec = it }
            }
        }
        "consent" -> AdmConsentDialog("User group consent", g.optLong("consent"), si.optLong("consent"), { dialog = null }) {
            dialog = null; edit("consent" to it)
        }
        "addusers" -> AddUsersDialog(ctrl, gid, links, users, onClose = { dialog = null }) { names ->
            dialog = null
            ctrl.send(JSONObject().put("action", "addusertousergroup").put("ugrpid", gid).put("usernames", JSONArray(names)), reply("Adding users"))
        }
    }
    editMesh?.let { mid ->
        AdmMeshRightsDialog(session, links, admDomain(gid), mid.ifEmpty { null }, { editMesh = null }) { meshId, value ->
            editMesh = null
            ctrl.send(JSONObject().put("action", "addmeshuser").put("meshid", meshId).put("meshname", session.meshes[meshId]?.name)
                .put("userids", JSONArray().put(gid)).put("meshadmin", value), reply("Changing the device group permissions"))
        }
    }
    editNode?.let { nid ->
        AdmDeviceRightsDialog(session, links, nid.ifEmpty { null }, { editNode = null }) { nodeId, value ->
            editNode = null
            ctrl.send(JSONObject().put("action", "adddeviceuser").put("nodeid", nodeId).put("nodename", session.node(nodeId)?.name)
                .put("userids", JSONArray().put(gid)).put("rights", value), reply("Changing the device permissions"))
        }
    }
    confirm?.let { (t, m, f) -> AdmConfirm(t, m, if (t.startsWith("Delete")) "Delete" else "Remove", { confirm = null }, f) }
}

/** web UI p51showAddUserDialog: comma separated user names, with suggestions from the user list. */
@Composable
private fun AddUsersDialog(ctrl: ControlConnection, gid: String, links: JSONObject, users: List<JSONObject>,
                           onClose: () -> Unit, onOk: (List<String>) -> Unit) {
    var text by remember { mutableStateOf("") }
    val dom = admDomain(gid)
    val cands = users.filter { admDomain(it.optString("_id")) == dom && !links.has(it.optString("_id")) }
        .sortedBy { it.optString("name").lowercase() }
    val parts = text.split(",").map { it.trim() }
    val key = parts.last().lowercase()
    val sugg = if (key.isEmpty() || cands.any { admShortId(it.optString("_id")) == key }) emptyList()
        else cands.filter { it.optString("name").lowercase().contains(key) || admShortId(it.optString("_id")).contains(key) }.take(8)
    AdmFormDialog("Add users to the group", ok = "Add", okEnabled = parts.all { it.isNotEmpty() && '"' !in it }, onDismiss = onClose,
        onOk = { onOk(parts.filter { it.isNotEmpty() }) }) {
        Text("Enter one or more user names, separated by commas.", style = MaterialTheme.typography.bodyMedium)
        OutlinedTextField(text, { text = it }, Modifier.fillMaxWidth().padding(top = 8.dp), singleLine = true,
            placeholder = { Text("user1, user2") })
        sugg.forEach { u ->
            val short = admShortId(u.optString("_id"))
            val label = u.optString("name").let { if (it.lowercase() == short) it else "$it  ($short)" }
            Text(label, Modifier.fillMaxWidth().clickable { text = (parts.dropLast(1) + short).joinToString(", ") }.padding(vertical = 10.dp, horizontal = 8.dp),
                color = MaterialTheme.colorScheme.primary)
        }
        if (ctrl.serverinfo.optLong("features") and 0x80000L != 0L) Text("Users need to sign in to this server once before they can be added.",
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
