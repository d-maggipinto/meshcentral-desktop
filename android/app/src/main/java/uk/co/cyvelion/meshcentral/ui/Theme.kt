// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

val OnlineGreen = Color(0xFF2E9E4F)
val OfflineGray = Color(0xFF8A9099)

// One brand palette (blue, neutral greys) instead of the wallpaper colours: the app looks the same on every phone.
private val Light = lightColorScheme(
    primary = Color(0xFF1F5FBF), onPrimary = Color.White,
    primaryContainer = Color(0xFFD9E4FA), onPrimaryContainer = Color(0xFF0B2A5C),
    secondary = Color(0xFF52607A), onSecondary = Color.White,
    secondaryContainer = Color(0xFFE1E7F2), onSecondaryContainer = Color(0xFF1B2638),
    tertiary = Color(0xFF00838F), tertiaryContainer = Color(0xFFCDEFF2), onTertiaryContainer = Color(0xFF00363B),
    background = Color(0xFFF5F7FB), onBackground = Color(0xFF181C22),
    surface = Color(0xFFF5F7FB), onSurface = Color(0xFF181C22),
    surfaceVariant = Color(0xFFE2E7EF), onSurfaceVariant = Color(0xFF5A6270),
    surfaceContainerLowest = Color.White, surfaceContainerLow = Color(0xFFFFFFFF),
    surfaceContainer = Color(0xFFEDF1F7), surfaceContainerHigh = Color(0xFFE6EBF2), surfaceContainerHighest = Color(0xFFDFE5EE),
    surfaceBright = Color(0xFFF5F7FB), surfaceDim = Color(0xFFD9DEE6),
    outline = Color(0xFF8D95A3), outlineVariant = Color(0xFFD5DBE4),
    error = Color(0xFFC62828), errorContainer = Color(0xFFFCDADA), onErrorContainer = Color(0xFF5F1111),
)
private val Dark = darkColorScheme(
    primary = Color(0xFF9DBEFF), onPrimary = Color(0xFF0A2C63),
    primaryContainer = Color(0xFF1F4785), onPrimaryContainer = Color(0xFFD9E4FA),
    secondary = Color(0xFFB8C4DB), onSecondary = Color(0xFF23304A),
    secondaryContainer = Color(0xFF2E3A50), onSecondaryContainer = Color(0xFFDDE5F4),
    tertiary = Color(0xFF6FD3DD), tertiaryContainer = Color(0xFF004F56), onTertiaryContainer = Color(0xFFCDEFF2),
    background = Color(0xFF0F1318), onBackground = Color(0xFFE1E5EC),
    surface = Color(0xFF0F1318), onSurface = Color(0xFFE1E5EC),
    surfaceVariant = Color(0xFF2A313B), onSurfaceVariant = Color(0xFFA9B1BE),
    surfaceContainerLowest = Color(0xFF0B0E12), surfaceContainerLow = Color(0xFF171C23),
    surfaceContainer = Color(0xFF1B2028), surfaceContainerHigh = Color(0xFF232933), surfaceContainerHighest = Color(0xFF2C333E),
    surfaceBright = Color(0xFF353C47), surfaceDim = Color(0xFF0F1318),
    outline = Color(0xFF737B88), outlineVariant = Color(0xFF353C47),
    error = Color(0xFFFFB4AB), errorContainer = Color(0xFF8C1D18), onErrorContainer = Color(0xFFFFDAD6),
)

private val AppShapes = Shapes(
    extraSmall = RoundedCornerShape(6.dp), small = RoundedCornerShape(10.dp), medium = RoundedCornerShape(14.dp),
    large = RoundedCornerShape(20.dp), extraLarge = RoundedCornerShape(28.dp),
)

@Composable
fun McdTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = if (isSystemInDarkTheme()) Dark else Light, shapes = AppShapes, content = content)
}
