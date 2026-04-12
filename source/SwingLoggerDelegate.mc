import Toybox.Lang;
import Toybox.WatchUi;

class SwingLoggerDelegate extends WatchUi.BehaviorDelegate {

    private var _view as SwingLoggerView;

    public function initialize(view as SwingLoggerView) {
        BehaviorDelegate.initialize();
        _view = view;
    }

    // SELECT button: start recording, or confirm before stopping
    public function onSelect() as Boolean {
        if (_view.isRecording()) {
            var confirm = new WatchUi.Confirmation("Stop recording?");
            WatchUi.pushView(confirm, new StopConfirmDelegate(_view), WatchUi.SLIDE_UP);
        } else {
            _view.startRecording();
        }
        return true;
    }

    // DOWN button marks a shot
    public function onNextPage() as Boolean {
        _view.markShot();
        return true;
    }

    // BACK button: confirm before exiting if recording
    public function onBack() as Boolean {
        if (_view.isRecording()) {
            var confirm = new WatchUi.Confirmation("Stop and exit?");
            WatchUi.pushView(confirm, new ExitConfirmDelegate(_view), WatchUi.SLIDE_UP);
            return true;
        }
        return false;
    }
}

// Confirmation delegate for stopping recording (SELECT during recording)
class StopConfirmDelegate extends WatchUi.ConfirmationDelegate {

    private var _view as SwingLoggerView;

    public function initialize(view as SwingLoggerView) {
        ConfirmationDelegate.initialize();
        _view = view;
    }

    public function onResponse(response as WatchUi.Confirm) as Boolean {
        if (response == WatchUi.CONFIRM_YES) {
            _view.stopRecording();
        }
        return true;
    }
}

// Confirmation delegate for exiting the app (BACK during recording)
class ExitConfirmDelegate extends WatchUi.ConfirmationDelegate {

    private var _view as SwingLoggerView;

    public function initialize(view as SwingLoggerView) {
        ConfirmationDelegate.initialize();
        _view = view;
    }

    public function onResponse(response as WatchUi.Confirm) as Boolean {
        if (response == WatchUi.CONFIRM_YES) {
            _view.stopRecording();
            System.exit();
        }
        return true;
    }
}
