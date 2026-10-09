// SPDX-License-Identifier: Apache-2.0
import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}

// One version number for every build of the app: the desktop package's __version__.
val appVersion: String = Regex("""__version__\s*=\s*"([0-9.]+)"""")
    .find(rootDir.resolve("../pkg/usr/share/meshcentral-desktop/mcdesktop/__init__.py").readText())!!
    .groupValues[1]
val appVersionCode: Int = appVersion.split(".").map { it.toInt() }.let { (a, b, c) -> a * 10000 + b * 100 + c }

// Release signing: keystore.properties (local, git-ignored) or MCD_KEYSTORE* environment variables (CI).
val signing = Properties().apply {
    rootDir.resolve("keystore.properties").takeIf { it.exists() }?.reader()?.use { load(it) }
}
fun signingValue(key: String, env: String): String? = signing.getProperty(key) ?: System.getenv(env)

android {
    namespace = "uk.co.cyvelion.meshcentral"
    compileSdk = 37

    defaultConfig {
        applicationId = "uk.co.cyvelion.meshcentral"
        minSdk = 26
        targetSdk = 36
        versionName = appVersion
        versionCode = appVersionCode
    }

    signingConfigs {
        val store = signingValue("storeFile", "MCD_KEYSTORE")
        if (store != null) {
            create("release") {
                storeFile = file(store)
                storePassword = signingValue("storePassword", "MCD_KEYSTORE_PASSWORD")
                keyAlias = signingValue("keyAlias", "MCD_KEY_ALIAS")
                keyPassword = signingValue("keyPassword", "MCD_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.findByName("release")
        }
        debug {
            applicationIdSuffix = ".debug"
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    // Local test rig (git-ignored app/src/rig): debug builds also trust the rig server's own root certificate.
    if (file("src/rig/res").exists()) {
        sourceSets["debug"].res.directories.add("src/rig/res")
        // -Prig: the release build too (local smoke test of the shrunk build only, never for a published APK); refused
        // together with real release signing, so a signed APK can never carry the test certificate
        if (project.hasProperty("rig")) {
            check(signingValue("storeFile", "MCD_KEYSTORE") == null) { "-Prig must not be combined with release signing" }
            sourceSets["release"].res.directories.add("src/rig/res")
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2026.09.00")
    implementation(composeBom)
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    debugImplementation("androidx.compose.ui:ui-tooling")
    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.core:core-ktx:1.19.1")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.11.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.11.0")
    implementation("androidx.navigation:navigation-compose:2.10.2")
    implementation("androidx.webkit:webkit:1.17.1")
    implementation("androidx.biometric:biometric:1.1.0")       // app lock (fingerprint, face, screen lock)
    // biometric 1.1.0 pulls fragment 1.2.5, whose FragmentActivity rejects the request codes of the current
    // activity-result API ("Can only use lower 16 bits"): every file / photo picker crashed. Pin a current one.
    implementation("androidx.fragment:fragment-ktx:1.9.1")
    implementation("com.squareup.okhttp3:okhttp:5.5.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.11.0")
}
