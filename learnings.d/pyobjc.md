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

## Under launchd the environment is not your shell's

Two things bit this project, both presenting as "works when I run it, broken
when it starts at login":

- **PATH is minimal** — `/usr/bin:/bin:/usr/sbin:/sbin`, with no Homebrew. A
  bare `subprocess.run(["betterdisplaycli", ...])` resolves from a terminal and
  raises `FileNotFoundError` from a LaunchAgent. Resolve helper binaries
  explicitly rather than trusting the inherited PATH, and set PATH in the plist
  as well.
- **stdout redirection produced nothing.** `StandardOutPath`/`StandardErrorPath`
  captured an empty file while the app ran correctly: same argv logged fine
  from a shell, `lsof` showed both fds on the right inode, and a `/bin/sh`
  probe agent redirected correctly. Never explained. A background agent should
  own its log file rather than depend on the launcher capturing streams.

Both failed *silently* in the sense that mattered — the app looked alive, and
only a feature deep inside it was broken.

Permissions are per-binary too: under launchd the responsible binary is
`.venv/bin/python`, not your terminal, so Accessibility and Input Monitoring
grants may need adding for that path specifically.

## macOS shows your app as "python" unless it is bundled

The name in Mission Control, the menu bar and Force Quit comes from
LaunchServices, which reads it from the bundle containing the running
executable. Patching `CFBundleName` on `NSBundle.mainBundle()` does nothing -
tested both before and after `NSApplication.sharedApplication()`, and
`localizedName()` still returns `python` either way.

A minimal bundle is enough, and the trick is what goes in `Contents/MacOS`:

    dmswitch.app/Contents/Info.plist            CFBundleName = dmswitch
    dmswitch.app/Contents/MacOS/dmswitch        symlink -> .venv/bin/python

Because the executable path lies inside the bundle, LaunchServices attributes
the process to it and `localizedName()` becomes `dmswitch`. A wrapper script
that `exec`s python does **not** work: the process image becomes the
interpreter at its own path, outside the bundle.

The cost is that Python can no longer find the venv - it looks for
`pyvenv.cfg` beside the executable - so `PYTHONPATH` has to supply
site-packages.

One pleasant surprise: TCC grants are keyed to the underlying binary, so
Accessibility and Input Monitoring granted to `.venv/bin/python` still applied
through the symlink. Bundling did not mean re-granting.

## Testing without a GUI

Most logic can be pulled out into plain functions and tested normally — the
keycode map, the wire format, held-key tracking, workspace planning, coordinate
conversion. For the parts that genuinely need AppKit, small fakes exposing
`frame()` and `localizedName()` stand in for `NSScreen` perfectly well.

A GUI app can still be exercised headlessly from a script: launch it in the
background, drive it with synthetic `CGEventPost` events, assert on remote
state, then `SIGTERM` it — with a `kill -9` fallback so a bug cannot strand the
person testing.
