import Toybox.Activity;
import Toybox.ActivityRecording;
import Toybox.FitContributor;
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.Math;
import Toybox.Sensor;
import Toybox.System;
import Toybox.Timer;
import Toybox.WatchUi;

class SwingLoggerView extends WatchUi.View {

    private var _dataTimer as Timer.Timer?;
    private var _session as ActivityRecording.Session?;
    private var _recording as Boolean = false;
    private var _seconds as Number = 0;

    // FIT developer fields
    private var _fPeakMag as FitContributor.Field?;
    private var _fMinMag as FitContributor.Field?;
    private var _fMeanMag as FitContributor.Field?;
    private var _fStdMag as FitContributor.Field?;
    private var _fMaxJerk as FitContributor.Field?;
    private var _fPeakX as FitContributor.Field?;
    private var _fPeakY as FitContributor.Field?;
    private var _fPeakZ as FitContributor.Field?;

    // Current readings for display
    private var _accelX as Number = 0;
    private var _accelY as Number = 0;
    private var _accelZ as Number = 0;

    // Per-second sample buffer (25 magnitude values)
    private var _magBuffer as Array<Float>;
    private var _peakX as Number = 0;
    private var _peakY as Number = 0;
    private var _peakZ as Number = 0;
    private var _prevMag as Float = 0.0;
    private var _maxJerk as Float = 0.0;
    private var _lastSecond as Number = 0;
    private var _displayMag as Float = 0.0;
    private var _displayJerk as Float = 0.0;

    public function initialize() {
        View.initialize();
        _magBuffer = [] as Array<Float>;
    }

    public function onLayout(dc as Dc) {
    }

    public function onShow() as Void {
        // Start the sensor polling timer when the view becomes visible.
        // This is also called after onHide() when a notification clears,
        // so the timer resumes automatically without losing the session.
        if (_dataTimer == null) {
            _dataTimer = new Timer.Timer();
            _dataTimer.start(method(:timerCallback), 40, true);
        }
    }

    public function onUpdate(dc as Dc) as Void {
        var width = dc.getWidth();
        var height = dc.getHeight();

        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);
        dc.clear();

        if (_recording) {
            dc.setColor(Graphics.COLOR_RED, Graphics.COLOR_TRANSPARENT);
            dc.drawText(width / 2, 5, Graphics.FONT_SMALL, "REC", Graphics.TEXT_JUSTIFY_CENTER);
        } else {
            dc.setColor(Graphics.COLOR_GREEN, Graphics.COLOR_TRANSPARENT);
            dc.drawText(width / 2, 5, Graphics.FONT_SMALL, "READY", Graphics.TEXT_JUSTIFY_CENTER);
        }

        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        var yStart = height / 2 - 55;
        dc.drawText(width / 2, yStart, Graphics.FONT_TINY, "Ax: " + _accelX, Graphics.TEXT_JUSTIFY_CENTER);
        dc.drawText(width / 2, yStart + 22, Graphics.FONT_TINY, "Ay: " + _accelY, Graphics.TEXT_JUSTIFY_CENTER);
        dc.drawText(width / 2, yStart + 44, Graphics.FONT_TINY, "Az: " + _accelZ, Graphics.TEXT_JUSTIFY_CENTER);

        dc.setColor(Graphics.COLOR_YELLOW, Graphics.COLOR_TRANSPARENT);
        dc.drawText(width / 2, yStart + 70, Graphics.FONT_TINY, "Mag: " + _displayMag.format("%.0f"), Graphics.TEXT_JUSTIFY_CENTER);

        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(width / 2, height - 50, Graphics.FONT_TINY, "Jerk: " + _displayJerk.format("%.0f"), Graphics.TEXT_JUSTIFY_CENTER);
        dc.drawText(width / 2, height - 30, Graphics.FONT_TINY, "Time: " + _seconds + "s", Graphics.TEXT_JUSTIFY_CENTER);
    }

    public function timerCallback() as Void {
        var info = Sensor.getInfo();

        if ((info has :accel) && (info.accel != null)) {
            var accel = info.accel as Array<Number>;
            _accelX = accel[0];
            _accelY = accel[1];
            _accelZ = accel[2];

            if (_recording) {
                // Compute magnitude
                var mag = Math.sqrt(
                    (_accelX.toFloat() * _accelX.toFloat()) +
                    (_accelY.toFloat() * _accelY.toFloat()) +
                    (_accelZ.toFloat() * _accelZ.toFloat())
                ).toFloat();

                // Track jerk (magnitude change between samples)
                var jerk = mag - _prevMag;
                if (jerk < 0.0) { jerk = -jerk; }
                if (jerk > _maxJerk) { _maxJerk = jerk; }
                _prevMag = mag;

                // Track peak absolute axes
                var ax = _accelX;
                var ay = _accelY;
                var az = _accelZ;
                if (ax < 0) { ax = -ax; }
                if (ay < 0) { ay = -ay; }
                if (az < 0) { az = -az; }
                if (ax > _peakX) { _peakX = ax; }
                if (ay > _peakY) { _peakY = ay; }
                if (az > _peakZ) { _peakZ = az; }

                // Buffer the magnitude
                _magBuffer.add(mag);
                _displayMag = mag;

                // Every ~1 second, compute features and write to FIT
                var now = System.getTimer();
                if (now - _lastSecond >= 1000) {
                    computeAndWriteFeatures();
                    _lastSecond = now;
                    _seconds++;
                }
            }
        }

        WatchUi.requestUpdate();
    }

    private function computeAndWriteFeatures() as Void {
        var n = _magBuffer.size();
        if (n == 0) {
            return;
        }

        // Compute mean
        var sum = 0.0 as Float;
        var peakMag = 0.0 as Float;
        var minMag = 99999.0 as Float;
        for (var i = 0; i < n; i++) {
            var v = _magBuffer[i] as Float;
            sum += v;
            if (v > peakMag) { peakMag = v; }
            if (v < minMag) { minMag = v; }
        }
        var meanMag = sum / n.toFloat();

        // Compute std deviation
        var sumSq = 0.0 as Float;
        for (var i = 0; i < n; i++) {
            var diff = (_magBuffer[i] as Float) - meanMag;
            sumSq += diff * diff;
        }
        var stdMag = Math.sqrt(sumSq / n.toFloat()).toFloat();

        // Write to FIT fields
        if (_fPeakMag != null) { _fPeakMag.setData(peakMag); }
        if (_fMinMag != null) { _fMinMag.setData(minMag); }
        if (_fMeanMag != null) { _fMeanMag.setData(meanMag); }
        if (_fStdMag != null) { _fStdMag.setData(stdMag); }
        if (_fMaxJerk != null) { _fMaxJerk.setData(_maxJerk); }
        if (_fPeakX != null) { _fPeakX.setData(_peakX); }
        if (_fPeakY != null) { _fPeakY.setData(_peakY); }
        if (_fPeakZ != null) { _fPeakZ.setData(_peakZ); }

        _displayJerk = _maxJerk;

        // Reset for next second
        _magBuffer = [] as Array<Float>;
        _peakX = 0;
        _peakY = 0;
        _peakZ = 0;
        _maxJerk = 0.0;
    }

    public function startRecording() as Void {
        if (!(Toybox has :ActivityRecording)) {
            return;
        }

        _session = ActivityRecording.createSession({
            :name => "GolfSwing",
            :sport => Activity.SPORT_GENERIC
        });

        _fPeakMag = _session.createField("peak_mag", 0,
            FitContributor.DATA_TYPE_FLOAT,
            {:mesgType => FitContributor.MESG_TYPE_RECORD, :units => "mg"});
        _fMinMag = _session.createField("min_mag", 1,
            FitContributor.DATA_TYPE_FLOAT,
            {:mesgType => FitContributor.MESG_TYPE_RECORD, :units => "mg"});
        _fMeanMag = _session.createField("mean_mag", 2,
            FitContributor.DATA_TYPE_FLOAT,
            {:mesgType => FitContributor.MESG_TYPE_RECORD, :units => "mg"});
        _fStdMag = _session.createField("std_mag", 3,
            FitContributor.DATA_TYPE_FLOAT,
            {:mesgType => FitContributor.MESG_TYPE_RECORD, :units => "mg"});
        _fMaxJerk = _session.createField("max_jerk", 4,
            FitContributor.DATA_TYPE_FLOAT,
            {:mesgType => FitContributor.MESG_TYPE_RECORD, :units => "mg"});
        _fPeakX = _session.createField("peak_x", 5,
            FitContributor.DATA_TYPE_SINT16,
            {:mesgType => FitContributor.MESG_TYPE_RECORD, :units => "mg"});
        _fPeakY = _session.createField("peak_y", 6,
            FitContributor.DATA_TYPE_SINT16,
            {:mesgType => FitContributor.MESG_TYPE_RECORD, :units => "mg"});
        _fPeakZ = _session.createField("peak_z", 7,
            FitContributor.DATA_TYPE_SINT16,
            {:mesgType => FitContributor.MESG_TYPE_RECORD, :units => "mg"});

        _session.start();
        _recording = true;
        _seconds = 0;
        _magBuffer = [] as Array<Float>;
        _peakX = 0;
        _peakY = 0;
        _peakZ = 0;
        _maxJerk = 0.0;
        _prevMag = 0.0;
        _lastSecond = System.getTimer();
    }

    public function stopRecording() as Void {
        if (_session != null) {
            if (_magBuffer.size() > 0) {
                computeAndWriteFeatures();
            }
            _session.stop();
            _session.save();
            _session = null;
        }
        _recording = false;
        _seconds = 0;
    }

    public function isRecording() as Boolean {
        return _recording;
    }

    public function onHide() as Void {
        // IMPORTANT: do NOT stop the recording session here.
        // onHide() fires for notifications, screen dim, widget swipes —
        // none of those mean the user wants to end the round. Killing the
        // session on hide caused notifications to silently end rounds.
        // The ActivityRecording.Session is an OS-level resource and survives
        // view hides on its own. Just pause the polling timer to save battery;
        // it gets restarted in onShow().
        if (_dataTimer != null) {
            _dataTimer.stop();
            _dataTimer = null;
        }
    }
}
