package com.taqueria.pos;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;

public class MainActivity extends Activity {
    private static final String PREFS_NAME = "TaqueriaPOSPrefs";
    private static final String KEY_SERVER_URL = "server_url";
    private static final String DEFAULT_URL = "http://10.0.2.2:8000";

    private WebView webView;
    private SharedPreferences prefs;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE);
        webView = new WebView(this);
        setContentView(webView);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);

        webView.setWebViewClient(new WebViewClient());
        webView.setWebChromeClient(new WebChromeClient());

        String savedUrl = prefs.getString(KEY_SERVER_URL, "");
        if (savedUrl.isEmpty()) {
            promptForServerUrl(DEFAULT_URL);
        } else {
            webView.loadUrl(savedUrl);
        }
    }

    private void promptForServerUrl(String currentUrl) {
        final EditText input = new EditText(this);
        input.setText(currentUrl);
        input.setHint("https://tu-taqueria.koyeb.app");

        new AlertDialog.Builder(this)
            .setTitle("Conectar a Nube / Servidor Taquería")
            .setMessage("Ingresa la URL de tu servidor en la nube o IP local:")
            .setView(input)
            .setCancelable(false)
            .setPositiveButton("Conectar", (dialog, which) -> {
                String url = input.getText().toString().trim();
                if (!url.startsWith("http://") && !url.startsWith("https://")) {
                    url = "https://" + url;
                }
                prefs.edit().putString(KEY_SERVER_URL, url).apply();
                webView.loadUrl(url);
            })
            .show();
    }

    @Override
    public void onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack();
        } else {
            promptForServerUrl(prefs.getString(KEY_SERVER_URL, DEFAULT_URL));
        }
    }
}
