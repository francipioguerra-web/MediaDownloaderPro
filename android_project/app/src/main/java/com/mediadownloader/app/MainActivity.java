package com.mediadownloader.app;

import android.Manifest;
import android.app.DownloadManager;
import android.content.Context;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.webkit.JavascriptInterface;
import android.webkit.URLUtil;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;
import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;

public class MainActivity extends AppCompatActivity {

    private WebView webView;
    private static final int PERMISSION_REQUEST_CODE = 100;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        requestStoragePermissions();

        webView = findViewById(R.id.webview);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(true);
        settings.setAllowContentAccess(true);
        settings.setDatabaseEnabled(true);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);

        webView.setWebViewClient(new WebViewClient());
        webView.addJavascriptInterface(new WebAppInterface(this), "AndroidApp");

        webView.setDownloadListener((url, userAgent, contentDisposition, mimetype, contentLength) -> {
            startAndroidDownload(url, URLUtil.guessFileName(url, contentDisposition, mimetype), mimetype, userAgent);
        });

        webView.loadUrl("file:///android_asset/index.html");
    }

    private void requestStoragePermissions() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.WRITE_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
                ActivityCompat.requestPermissions(this, new String[]{
                        Manifest.permission.WRITE_EXTERNAL_STORAGE,
                        Manifest.permission.READ_EXTERNAL_STORAGE
                }, PERMISSION_REQUEST_CODE);
            }
        }
    }

    private void startAndroidDownload(String url, String filename, String mimetype, String userAgent) {
        try {
            if (filename == null || filename.trim().isEmpty()) {
                filename = "Media_" + System.currentTimeMillis() + ".mp4";
            }

            DownloadManager.Request request = new DownloadManager.Request(Uri.parse(url));
            if (mimetype != null && !mimetype.isEmpty()) {
                request.setMimeType(mimetype);
            }
            if (userAgent != null && !userAgent.isEmpty()) {
                request.addRequestHeader("User-Agent", userAgent);
            }

            request.setDescription("Scaricamento file multimediale in corso...");
            request.setTitle(filename);
            request.setAllowedOverRoaming(true);
            request.setAllowedOverMetered(true);
            request.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
            request.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, filename);

            DownloadManager dm = (DownloadManager) getSystemService(DOWNLOAD_SERVICE);
            if (dm != null) {
                dm.enqueue(request);
                Toast.makeText(MainActivity.this, "🚀 Download avviato! Controlla le notifiche di Android.", Toast.LENGTH_LONG).show();
            }
        } catch (Exception ex) {
            Toast.makeText(MainActivity.this, "Errore avvio download: " + ex.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    public class WebAppInterface {
        private Context context;

        WebAppInterface(Context c) {
            context = c;
        }

        @JavascriptInterface
        public void showToast(String toast) {
            runOnUiThread(() -> Toast.makeText(context, toast, Toast.LENGTH_SHORT).show());
        }

        @JavascriptInterface
        public void downloadFile(String url, String filename) {
            runOnUiThread(() -> startAndroidDownload(url, filename, "video/mp4", null));
        }
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
