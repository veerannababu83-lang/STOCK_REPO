package com.satya.stockcharts;

import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.view.KeyEvent;
import android.view.WindowManager;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

public class MainActivity extends Activity {
    WebView w;
    final Handler h = new Handler();

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        w = new WebView(this);
        setContentView(w);
        WebSettings s = w.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        w.setBackgroundColor(0xFF0F1216);
        w.setWebViewClient(new WebViewClient() {
            // server asleep / no internet yet: keep retrying every 5 s
            @Override public void onReceivedError(WebView v, WebResourceRequest r, WebResourceError e) {
                if (r.isForMainFrame()) retry();
            }
            @Override public void onReceivedHttpError(WebView v, WebResourceRequest r, WebResourceResponse e) {
                if (r.isForMainFrame()) retry();
            }
        });
        w.loadUrl(BuildConfig.APP_URL);
    }

    void retry() {
        h.removeCallbacksAndMessages(null);
        h.postDelayed(new Runnable() { public void run() { w.loadUrl(BuildConfig.APP_URL); } }, 5000);
    }

    void js(String code) { w.evaluateJavascript(code, null); }

    @Override public boolean dispatchKeyEvent(KeyEvent e) {
        if (e.getAction() == KeyEvent.ACTION_DOWN) {
            switch (e.getKeyCode()) {
                case KeyEvent.KEYCODE_DPAD_RIGHT:
                case KeyEvent.KEYCODE_DPAD_DOWN:
                case KeyEvent.KEYCODE_MEDIA_FAST_FORWARD:
                    if (e.getRepeatCount() == 0) js("typeof go==='function'&&go(1)");
                    return true;
                case KeyEvent.KEYCODE_DPAD_LEFT:
                case KeyEvent.KEYCODE_DPAD_UP:
                case KeyEvent.KEYCODE_MEDIA_REWIND:
                    if (e.getRepeatCount() == 0) js("typeof go==='function'&&go(-1)");
                    return true;
                case KeyEvent.KEYCODE_MENU:   // the three-line button on the Fire remote
                    w.loadUrl(BuildConfig.APP_URL);
                    return true;
            }
        }
        return super.dispatchKeyEvent(e);
    }

    @Override protected void onResume() { super.onResume(); w.onResume(); }
    @Override protected void onPause() { w.onPause(); super.onPause(); }
    @Override protected void onDestroy() { h.removeCallbacksAndMessages(null); w.destroy(); super.onDestroy(); }
}
