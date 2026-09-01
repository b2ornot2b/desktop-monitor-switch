# PyObjC

## A bare NSApplication cannot be quit

Building an `NSApplication` from Python gives you no main menu, and therefore
**no key equivalent bound to Quit** — `Cmd+Q` silently does nothing. Combined
with a full-screen window (whose close button is hidden) and `Ctrl+C` not
working either, the result is an app with no way out at all. That happened
here, with the app holding the keyboard at the time.

```python
main_menu = AppKit.NSMenu.alloc().init()
item = AppKit.NSMenuItem.alloc().init()
main_menu.addItem_(item)
menu = AppKit.NSMenu.alloc().init()
menu.addItemWithTitle_action_keyEquivalent_("Quit", b"terminate:", "q")
item.setSubmenu_(menu)
AppKit.NSApp().setMainMenu_(main_menu)
```

**Any full-screen PyObjC app needs a quit path before it is first run.**

## Ctrl+C does not work under `NSApplication.run()`

Python only runs signal handlers between bytecodes, and the Cocoa run loop sits
in C, so a `SIGINT` handler never gets a chance. Set a flag in the handler and
poll it from a timer, which gives the interpreter a moment to breathe:

```python
signal.signal(signal.SIGINT, lambda *_: globals().__setitem__("_interrupted", True))
AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
    0.25, delegate, b"checkForInterrupt:", None, True)
```

Calling into AppKit from the handler itself is not safe; the timer callback is
the right place to call `terminate_`.

## Methods with arguments need `@objc.python_method`

On an `NSObject` subclass, PyObjC tries to expose methods as selectors and
matches on argument count. A helper taking one argument whose name has no
trailing colon is rejected outright:

```
objc.BadPrototypeError: '_reevaluate' expects 0 arguments, ... has 1
```

Mark anything that is purely internal:

```python
@objc.python_method
def _reevaluate(self, reason: str): ...
```

Notification handlers *are* selectors and must take exactly one argument, and
are registered by bytes name: `b"activeSpaceChanged:"`.

## Two notification centres

They are not interchangeable:

| notification | centre |
|---|---|
| `NSWorkspaceActiveSpaceDidChangeNotification` | `NSWorkspace.sharedWorkspace().notificationCenter()` |
| `NSApplicationDidResignActiveNotification` | `NSNotificationCenter.defaultCenter()` |

## Event tap callbacks

A bound method works fine as a `CGEventTapCreate` callback. Add the run loop
source in `applicationDidFinishLaunching_`, where the current run loop is the
main one, and keep a reference to both the tap and the source — dropping either
stops delivery with no error.

## Testing without a GUI

Most logic can be pulled out into plain functions and tested normally — the
keycode map, the wire format, held-key tracking, workspace planning, coordinate
conversion. For the parts that genuinely need AppKit, small fakes exposing
`frame()` and `localizedName()` stand in for `NSScreen` perfectly well.

A GUI app can still be exercised headlessly from a script: launch it in the
background, drive it with synthetic `CGEventPost` events, assert on remote
state, then `SIGTERM` it — with a `kill -9` fallback so a bug cannot strand the
person testing.
