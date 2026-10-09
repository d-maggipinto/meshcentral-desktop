# WebView JavaScript bridges are called by name from the pages.
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}
