// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

import androidx.compose.foundation.Image
import androidx.compose.material.icons.filled.Laptop
import androidx.compose.material.icons.filled.Storage
import androidx.compose.material.icons.filled.Router
import androidx.compose.material.icons.filled.DeveloperBoard
import androidx.compose.material.icons.filled.CloudQueue
import uk.co.cyvelion.meshcentral.data.ServerIcons
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DesktopWindows
import androidx.compose.material.icons.filled.Dns
import androidx.compose.material.icons.filled.PhoneAndroid
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import uk.co.cyvelion.meshcentral.data.Node

/** Built-in icon for the device type the user chose in MeshCentral (node.icon 1..8, the web UI's icon set). */
private fun typeIcon(icon: Int): ImageVector = when (icon) {
    2 -> Icons.Filled.Laptop
    3 -> Icons.Filled.PhoneAndroid
    4 -> Icons.Filled.Dns
    5 -> Icons.Filled.Storage
    6 -> Icons.Filled.Router
    7 -> Icons.Filled.DeveloperBoard
    8 -> Icons.Filled.CloudQueue                                   // virtual machine
    else -> Icons.Filled.DesktopWindows
}

/** Accent colour by operating system (the tile behind the built-in icon). */
private fun osColor(n: Node): Color = when (n.osFamily) {
    "Windows" -> Color(0xFF0078D4)
    "Linux" -> Color(0xFFE2702A)
    "macOS" -> Color(0xFF6E7681)
    "Android" -> Color(0xFF2E9E4F)
    "BSD" -> Color(0xFFB0283A)
    else -> Color(0xFF52607A)
}

private val GRAY = androidx.compose.ui.graphics.ColorFilter.colorMatrix(androidx.compose.ui.graphics.ColorMatrix().apply { setToSaturation(0f) })

/**
 * The device's icon with an online dot: the server's own icon for the device type (ServerIcons, like the web UI and
 * the desktop app), else a built-in icon of that type on a tile in the OS colour. Grey and faded while offline.
 */
@Composable
fun OsAvatar(n: Node, size: Dp = 44.dp) {
    val img = ServerIcons.of(n.icon)
    val color = osColor(n)
    Box(Modifier.size(size + 4.dp)) {
        if (img != null) {
            Image(img, null, Modifier.size(size).alpha(if (n.online) 1f else 0.5f), colorFilter = if (n.online) null else GRAY)
        } else {
            Box(Modifier.size(size).background(color.copy(alpha = if (n.online) 0.14f else 0.08f), RoundedCornerShape(size * 0.3f)),
                contentAlignment = Alignment.Center) {
                Icon(typeIcon(n.icon), null, Modifier.size(size * 0.55f).alpha(if (n.online) 1f else 0.45f), tint = color)
            }
        }
        Box(Modifier.align(Alignment.BottomEnd).size(size * 0.3f)
            .border(2.dp, MaterialTheme.colorScheme.surfaceContainerLow, CircleShape)
            .padding(2.dp).background(if (n.online) OnlineGreen else OfflineGray, CircleShape))
    }
}

@Composable
fun StatusPill(online: Boolean, text: String = if (online) "Online" else "Offline") {
    val c = if (online) OnlineGreen else OfflineGray
    Row(Modifier.background(c.copy(alpha = 0.13f), CircleShape).padding(horizontal = 10.dp, vertical = 3.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        Box(Modifier.size(7.dp).background(c, CircleShape))
        Text(text, style = MaterialTheme.typography.labelMedium, color = if (online) c else MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

/** A rounded white block (on the grey page) with an optional small heading. */
@Composable
fun SectionCard(modifier: Modifier = Modifier, title: String? = null, content: @Composable ColumnScope.() -> Unit) {
    Column(modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp)) {
        if (title != null) Text(title.uppercase(), Modifier.padding(start = 4.dp, bottom = 6.dp, top = 6.dp),
            style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.SemiBold,
            color = MaterialTheme.colorScheme.primary)
        Surface(shape = MaterialTheme.shapes.large, color = MaterialTheme.colorScheme.surfaceContainerLow,
            tonalElevation = 0.dp, shadowElevation = 0.dp, modifier = Modifier.fillMaxWidth()
                .border(1.dp, MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f), MaterialTheme.shapes.large)) {
            Column(content = content)
        }
    }
}

/** Label / value line inside a SectionCard. */
@Composable
fun InfoLine(label: String, value: String, last: Boolean = false) {
    Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp)) {
        Text(label, Modifier.width(130.dp), style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
    }
    if (!last) HorizontalDivider(Modifier.padding(start = 16.dp), color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f))
}

/** A big square-ish action button (icon on a tinted circle, label under it). */
@Composable
fun ActionTile(label: String, icon: ImageVector, enabled: Boolean, modifier: Modifier = Modifier,
               tint: Color = MaterialTheme.colorScheme.primary, onClick: () -> Unit) {
    Surface(modifier = modifier.alpha(if (enabled) 1f else 0.4f), shape = MaterialTheme.shapes.large,
        color = MaterialTheme.colorScheme.surfaceContainerLow,
        border = androidx.compose.foundation.BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f))) {
        Column(Modifier.fillMaxWidth().clickable(enabled = enabled, onClick = onClick).padding(vertical = 14.dp),
            horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Box(Modifier.size(42.dp).background(tint.copy(alpha = 0.12f), CircleShape), contentAlignment = Alignment.Center) {
                Icon(icon, null, Modifier.size(22.dp), tint = tint)
            }
            Text(label, style = MaterialTheme.typography.labelLarge, maxLines = 1)
        }
    }
}
