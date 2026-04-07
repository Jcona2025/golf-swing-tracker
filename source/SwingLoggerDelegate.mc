import Toybox.Lang;
import Toybox.WatchUi;

class SwingLoggerDelegate extends WatchUi.BehaviorDelegate {

    private var _view as SwingLoggerView;

    public function initialize(view as SwingLoggerView) {
        BehaviorDelegate.initialize();
        _view = view;
    }

    // START button toggles recording
    public function onSelect() as Boolean {
        if (_view.isRecording()) {
            _view.stopRecording();
        } else {
            _view.startRecording();
        }
        return true;
    }

    // BACK button exits (stop recording first if active)
    public function onBack() as Boolean {
        if (_view.isRecording()) {
            _view.stopRecording();
            return true;
        }
        return false;
    }
}
