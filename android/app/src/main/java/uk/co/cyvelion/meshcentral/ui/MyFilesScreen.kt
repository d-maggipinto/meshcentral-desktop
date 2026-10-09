// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

import android.net.Uri
import android.provider.OpenableColumns
import android.util.Base64
import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.InsertDriveFile
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.ContentCut
import androidx.compose.material.icons.filled.ContentPaste
import androidx.compose.material.icons.filled.CreateNewFolder
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.DriveFileRenameOutline
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.FolderShared
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Upload
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import org.json.JSONArray
import org.json.JSONObject
import uk.co.cyvelion.meshcentral.McdApp
import uk.co.cyvelion.meshcentral.data.Session
import uk.co.cyvelion.meshcentral.data.Site
import java.text.DateFormat
import java.util.Date

/** The server's limit for the websocket 'get' (fileop get): small files can be read without a web session. */
private const val EDIT_MAX = 200 * 1024

/** t: 1 user root, 4 device group root, 2 folder, 3 file; s size, d modified (ms, 111 = folder placeholder). */
private data class SrvEntry(val key: String, val name: String, val type: Int, val size: Long, val date: Long) {
    val isDir get() = type != 3
}

private fun treeSize(f: JSONObject?): Long {
    if (f == null) return 0
    var total = 0L
    f.keys().forEach { k -> f.optJSONObject(k)?.let { e -> total += e.optLong("s"); total += treeSize(e.optJSONObject("f")) } }
    return total
}

private class Clip(val op: String, val path: List<String>, val names: List<String>)

/**
 * Server file storage, "My Files" in the web UI (server_files_panel.py): a personal folder plus one per device group
 * with the group's server-files right. {action:'files'} answers (and is pushed after every change) with the whole
 * tree; changes are {action:'fileoperation', fileop, path:[rootid, sub...]}. Transfers are HTTP: uploadfile.ashx with
 * the control channel's auth cookie, downloadfile.ashx with a private web sign-in.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MyFilesScreen(app: McdApp, session: Session, onBack: () -> Unit) {
    val ctrl = session.ctrl
    val ctx = LocalContext.current
    val allowed = Site.has(ctrl.userinfo, Site.FILEACCESS)
    var tree by remember { mutableStateOf<JSONObject?>(null) }
    var path by remember { mutableStateOf(listOf<String>()) }
    var menuFor by remember { mutableStateOf<SrvEntry?>(null) }
    var renameOf by remember { mutableStateOf<SrvEntry?>(null) }
    var deleteOf by remember { mutableStateOf<SrvEntry?>(null) }
    var newFolder by remember { mutableStateOf(false) }
    var clip by remember { mutableStateOf<Clip?>(null) }
    var progress by remember { mutableStateOf<Pair<String, Float?>?>(null) }
    var editing by remember { mutableStateOf<Triple<List<String>, String, String>?>(null) }   // path, file, text
    var pendingDownload by remember { mutableStateOf<SrvEntry?>(null) }
    var pendingUploads by remember { mutableStateOf<List<Uri>?>(null) }
    val web = remember { ServerWebSession(ctrl) }
    val editWaits = remember { HashSet<String>() }
    // callbacks made in an earlier composition must see the current folder
    val cur = remember { arrayOf(listOf<String>()) }
    cur[0] = path

    fun folder(p: List<String>): JSONObject? {
        var f = tree?.optJSONObject("f") ?: return null
        for (k in p) { val e = f.optJSONObject(k) ?: return null; f = e.optJSONObject("f") ?: JSONObject() }
        return f
    }
    fun op(vararg pairs: Pair<String, Any?>, at: List<String> = cur[0]) =
        ctrl.send(JSONObject().put("action", "fileoperation").put("path", JSONArray(at)).apply { pairs.forEach { (k, v) -> put(k, v) } })

    DisposableEffect(Unit) {
        val onFiles: (JSONObject) -> Unit = { m ->
            tree = m.optJSONObject("filetree") ?: JSONObject()
            var p = cur[0]
            while (p.isNotEmpty() && folder(p) == null) p = p.dropLast(1)     // stay in the folder if it still exists
            path = p
        }
        val onOp: (JSONObject) -> Unit = { m ->
            if (m.optString("fileop") == "get" && m.has("data")) {
                val p = m.optJSONArray("path")?.let { a -> (0 until a.length()).map { a.optString(it) } } ?: emptyList()
                val k = p.joinToString("/") + "|" + m.optString("file")
                if (editWaits.remove(k)) {
                    val text = try { String(Base64.decode(m.optString("data"), Base64.DEFAULT), Charsets.UTF_8) } catch (e: Exception) { null }
                    if (text == null || text.contains('�')) Toast.makeText(ctx, "This is not a UTF-8 text file.", Toast.LENGTH_SHORT).show()
                    else editing = Triple(p, m.optString("file"), text)
                }
            }
        }
        if (allowed) {
            ctrl.on("files", onFiles)
            ctrl.on("fileoperation", onOp)
            ctrl.send("action" to "files")
        }
        onDispose { ctrl.off("files", onFiles); ctrl.off("fileoperation", onOp) }
    }

    val download = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/octet-stream")) { uri ->
        val e = pendingDownload ?: return@rememberLauncherForActivityResult
        pendingDownload = null
        if (uri == null) return@rememberLauncherForActivityResult
        val at = cur[0]
        val out = try { ctx.contentResolver.openOutputStream(uri) } catch (ex: Exception) { null }
        if (out == null) { Toast.makeText(ctx, "Cannot write the file.", Toast.LENGTH_SHORT).show(); return@rememberLauncherForActivityResult }
        progress = "Downloading ${e.name}" to null
        val link = (at + e.key).joinToString("/")
        web.fetch("/downloadfile.ashx?link=" + Uri.encode(link), out, { d, t -> progress = "Downloading ${e.name}" to (if (t > 0) d.toFloat() / t else null) }) { err ->
            progress = null
            if (err == null) { Toast.makeText(ctx, "Downloaded ${e.name}", Toast.LENGTH_SHORT).show(); return@fetch }
            if (e.size >= EDIT_MAX) { Toast.makeText(ctx, "Download of ${e.name} failed: $err", Toast.LENGTH_LONG).show(); return@fetch }
            // no web sign-in (two-factor account): small files come over the control channel
            var cb: ((JSONObject) -> Unit)? = null
            cb = { m ->
                val p = m.optJSONArray("path")?.let { a -> (0 until a.length()).map { a.optString(it) } }
                if (m.optString("fileop") == "get" && m.optString("file") == e.key && p == at && m.has("data")) {
                    ctrl.off("fileoperation", cb!!)
                    val ok = runCatching { ctx.contentResolver.openOutputStream(uri, "wt")?.use { it.write(Base64.decode(m.optString("data"), Base64.DEFAULT)) } }.isSuccess
                    Toast.makeText(ctx, if (ok) "Downloaded ${e.name}" else "Cannot write the file.", Toast.LENGTH_SHORT).show()
                }
            }
            ctrl.on("fileoperation", cb)
            op("fileop" to "get", "file" to e.key, at = at)
        }
    }

    fun uploadNext(queue: List<Uri>, at: List<String>) {
        val uri = queue.firstOrNull()
        if (uri == null) { progress = null; ctrl.send("action" to "files"); Toast.makeText(ctx, "Upload complete", Toast.LENGTH_SHORT).show(); return }
        var name = "file"
        var size = -1L
        ctx.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { c ->
            if (c.moveToFirst()) { c.getString(0)?.let { name = it }; if (!c.isNull(1)) size = c.getLong(1) }
        }
        val input = try { ctx.contentResolver.openInputStream(uri) } catch (e: Exception) { null }
        if (input == null) { Toast.makeText(ctx, "Cannot read $name", Toast.LENGTH_SHORT).show(); uploadNext(queue.drop(1), at); return }
        progress = "Uploading $name" to null
        web.postFile("/uploadfile.ashx", mapOf("link" to Uri.encode(at.joinToString("/"))), "files", name, size, input,
            { d, t -> progress = "Uploading $name" to (if (t > 0) d.toFloat() / t else null) }) { err ->
            if (err != null) { progress = null; Toast.makeText(ctx, "Upload of $name failed: $err", Toast.LENGTH_LONG).show() }
            else uploadNext(queue.drop(1), at)
        }
    }
    val pick = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        if (uris.isEmpty()) return@rememberLauncherForActivityResult
        val existing = folder(cur[0])?.keys()?.asSequence()?.toSet() ?: emptySet()
        val clash = uris.mapNotNull { u ->
            ctx.contentResolver.query(u, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c -> if (c.moveToFirst()) c.getString(0) else null }
        }.filter { it in existing }
        if (clash.isNotEmpty()) pendingUploads = uris else uploadNext(uris, cur[0])
    }

    BackHandler(enabled = path.isNotEmpty()) { path = path.dropLast(1) }

    // breadcrumb names
    val names = buildList {
        var f = tree?.optJSONObject("f")
        for (k in path) { val e = f?.optJSONObject(k); add(e?.optString("n")?.ifEmpty { null } ?: k); f = e?.optJSONObject("f") }
    }
    val entries = folder(path)?.let { f ->
        f.keys().asSequence().mapNotNull { k ->
            val e = f.optJSONObject(k) ?: return@mapNotNull null
            SrvEntry(k, e.optString("n").ifEmpty { k }, e.optInt("t", 3), e.optLong("s"), e.optLong("d"))
        }.sortedWith(compareBy<SrvEntry>({ !it.isDir }, { it.name.lowercase() })).toList()
    }
    val root = path.firstOrNull()?.let { tree?.optJSONObject("f")?.optJSONObject(it) }

    Scaffold(topBar = {
        TopAppBar(
            title = {
                Column {
                    Text(names.lastOrNull() ?: "Files", maxLines = 1, overflow = TextOverflow.Ellipsis)
                    val sub = if (root != null) {
                        val q = root.optLong("maxbytes", 0)
                        "${entries?.size ?: 0} items · ${fmtSize(treeSize(root.optJSONObject("f")))}" + (if (q > 0) " of ${fmtSize(q)}" else "")
                    } else "Server file storage"
                    Text(sub, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            },
            navigationIcon = { IconButton({ if (path.isNotEmpty()) path = path.dropLast(1) else onBack() }) {
                Icon(if (path.isNotEmpty()) Icons.Filled.ArrowUpward else Icons.AutoMirrored.Filled.ArrowBack, if (path.isNotEmpty()) "Up" else "Back") } },
            actions = {
                if (allowed) {
                    if (clip != null && path.isNotEmpty()) IconButton({
                        val c = clip!!
                        if (c.path == path) Toast.makeText(ctx, "Already in this folder", Toast.LENGTH_SHORT).show()
                        else { op("fileop" to c.op, "scpath" to JSONArray(c.path), "names" to JSONArray(c.names)); if (c.op == "move") clip = null }
                    }) { Icon(Icons.Filled.ContentPaste, "Paste here") }
                    IconButton({ ctrl.send("action" to "files") }) { Icon(Icons.Filled.Refresh, "Refresh") }
                    if (path.isNotEmpty()) {
                        IconButton({ newFolder = true }) { Icon(Icons.Filled.CreateNewFolder, "New folder") }
                        IconButton({ pick.launch(arrayOf("*/*")) }, enabled = progress == null) { Icon(Icons.Filled.Upload, "Upload files") }
                    }
                }
            })
    }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad)) {
            if (!allowed) {
                Text("Your account does not have access to server files (\"My Files\" in the web interface). An administrator can grant the Server Files permission.",
                    Modifier.padding(24.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
                return@Column
            }
            if (path.isNotEmpty()) Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Text("Root", Modifier.clickable { path = emptyList() }.padding(4.dp), color = MaterialTheme.colorScheme.primary,
                    style = MaterialTheme.typography.labelLarge)
                names.forEachIndexed { i, n ->
                    Text("›", Modifier.padding(horizontal = 2.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(n, Modifier.clickable { path = path.take(i + 1) }.padding(4.dp),
                        color = if (i == names.size - 1) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.primary,
                        style = MaterialTheme.typography.labelLarge, maxLines = 1)
                }
            }
            progress?.let { (text, f) ->
                Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp)) {
                    Text(text, style = MaterialTheme.typography.bodySmall)
                    if (f == null) LinearProgressIndicator(Modifier.fillMaxWidth().padding(top = 4.dp))
                    else LinearProgressIndicator({ f.coerceIn(0f, 1f) }, Modifier.fillMaxWidth().padding(top = 4.dp))
                }
            }
            clip?.let { c ->
                Row(Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.secondaryContainer).padding(horizontal = 16.dp, vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    Text("${if (c.op == "move") "Cut" else "Copied"} ${c.names.size} item(s): open a folder and paste", Modifier.weight(1f),
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSecondaryContainer)
                    TextButton({ clip = null }) { Text("Cancel") }
                }
            }
            when {
                tree == null -> Box(Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
                entries.isNullOrEmpty() -> Text(if (path.isEmpty()) "No storage areas." else "This folder is empty.",
                    Modifier.padding(24.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
                else -> LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
                    items(entries, key = { it.key }) { e ->
                        Row(Modifier.fillMaxWidth().clickable {
                            if (e.isDir) path = path + e.key else menuFor = e
                        }.padding(start = 16.dp, end = 4.dp, top = 8.dp, bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                            val icon = when (e.type) { 1 -> Icons.Filled.Home; 4 -> Icons.Filled.FolderShared; 2 -> Icons.Filled.Folder
                                else -> Icons.AutoMirrored.Filled.InsertDriveFile }
                            Box(Modifier.size(40.dp).background(MaterialTheme.colorScheme.primary.copy(alpha = 0.10f), RoundedCornerShape(12.dp)),
                                contentAlignment = Alignment.Center) {
                                Icon(icon, null, tint = MaterialTheme.colorScheme.primary)
                            }
                            Column(Modifier.weight(1f).padding(start = 12.dp)) {
                                Text(e.name, style = MaterialTheme.typography.bodyLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                val sub = listOfNotNull(if (e.isDir) null else fmtSize(e.size),
                                    if (e.date > 0 && e.date != 111L) DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT).format(Date(e.date)) else null,
                                    when (e.type) { 1 -> "Personal storage"; 4 -> "Device group storage"; else -> null })
                                if (sub.isNotEmpty()) Text(sub.joinToString("  ·  "), style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                            }
                            if (path.isNotEmpty()) Box {
                                IconButton({ menuFor = e }) { Icon(Icons.Filled.MoreVert, "Actions") }
                                DropdownMenu(menuFor == e, { menuFor = null }) {
                                    if (!e.isDir) DropdownMenuItem({ Text("Download") }, leadingIcon = { Icon(Icons.Filled.Download, null) }, onClick = {
                                        menuFor = null; pendingDownload = e; download.launch(e.name)
                                    })
                                    if (!e.isDir && e.size < EDIT_MAX) DropdownMenuItem({ Text("Edit as text") }, leadingIcon = { Icon(Icons.Filled.Edit, null) }, onClick = {
                                        menuFor = null; editWaits.add(path.joinToString("/") + "|" + e.key); op("fileop" to "get", "file" to e.key)
                                    })
                                    DropdownMenuItem({ Text("Rename") }, leadingIcon = { Icon(Icons.Filled.DriveFileRenameOutline, null) },
                                        onClick = { menuFor = null; renameOf = e })
                                    DropdownMenuItem({ Text("Cut") }, leadingIcon = { Icon(Icons.Filled.ContentCut, null) },
                                        onClick = { menuFor = null; clip = Clip("move", path, listOf(e.key)) })
                                    DropdownMenuItem({ Text("Copy") }, leadingIcon = { Icon(Icons.Filled.ContentCopy, null) },
                                        onClick = { menuFor = null; clip = Clip("copy", path, listOf(e.key)) })
                                    DropdownMenuItem({ Text("Delete", color = MaterialTheme.colorScheme.error) },
                                        leadingIcon = { Icon(Icons.Filled.Delete, null, tint = MaterialTheme.colorScheme.error) },
                                        onClick = { menuFor = null; deleteOf = e })
                                }
                            }
                        }
                        HorizontalDivider(Modifier.padding(start = 68.dp), color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f))
                    }
                }
            }
        }
    }

    if (newFolder) TextDialog("New folder", "", "Create", { newFolder = false }) { n ->
        newFolder = false
        if (n.isNotBlank()) op("fileop" to "createfolder", "newfolder" to n.trim())
    }
    renameOf?.let { e ->
        TextDialog("Rename", e.key, "Rename", { renameOf = null }) { n ->
            renameOf = null
            if (n.isNotBlank() && n.trim() != e.key) op("fileop" to "rename", "oldname" to e.key, "newname" to n.trim())
        }
    }
    deleteOf?.let { e ->
        AlertDialog(onDismissRequest = { deleteOf = null }, title = { Text("Delete ${e.name}?") },
            text = { Text(if (e.isDir) "The folder and everything in it are deleted from the server." else "The file is deleted from the server.") },
            confirmButton = { TextButton({
                deleteOf = null
                // the server's recursive delete only handles folders (on a file it fails silently)
                op("fileop" to "delete", "delfiles" to JSONArray(listOf(e.key)), "rec" to e.isDir)
            }) { Text("Delete", color = MaterialTheme.colorScheme.error) } },
            dismissButton = { TextButton({ deleteOf = null }) { Text("Cancel") } })
    }
    pendingUploads?.let { uris ->
        AlertDialog(onDismissRequest = { pendingUploads = null }, title = { Text("Overwrite existing files?") },
            text = { Text("A file with the same name is already in this folder.") },
            confirmButton = { TextButton({ pendingUploads = null; uploadNext(uris, cur[0]) }) { Text("Overwrite", color = MaterialTheme.colorScheme.error) } },
            dismissButton = { TextButton({ pendingUploads = null }) { Text("Cancel") } })
    }
    editing?.let { (p, file, text) ->
        var value by remember(p, file) { mutableStateOf(text) }
        AlertDialog(onDismissRequest = { editing = null }, title = { Text(file, maxLines = 1, overflow = TextOverflow.Ellipsis) },
            text = {
                OutlinedTextField(value, { value = it }, Modifier.fillMaxWidth().heightIn(min = 200.dp, max = 420.dp),
                    textStyle = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace))
            },
            confirmButton = { TextButton({
                editing = null
                if (value != text) ctrl.send(JSONObject().put("action", "fileoperation").put("fileop", "set").put("path", JSONArray(p))
                    .put("file", file).put("data", Base64.encodeToString(value.toByteArray(Charsets.UTF_8), Base64.NO_WRAP)))
            }) { Text("Save", fontWeight = FontWeight.SemiBold) } },
            dismissButton = { TextButton({ editing = null }) { Text("Cancel") } })
    }
}
