import Toybox.Application;
import Toybox.Lang;
import Toybox.WatchUi;

class SwingLoggerApp extends Application.AppBase {

    public function initialize() {
        AppBase.initialize();
    }

    public function onStart(state as Dictionary?) as Void {
    }

    public function onStop(state as Dictionary?) as Void {
    }

    public function getInitialView() as [Views] or [Views, InputDelegates] {
        var mainView = new $.SwingLoggerView();
        var viewDelegate = new $.SwingLoggerDelegate(mainView);
        return [mainView, viewDelegate];
    }
}
