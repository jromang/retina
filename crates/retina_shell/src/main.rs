//! Native shell for Retina — one window, one webview, the URL of the Python server.
//!
//! # Why tao + wry rather than Tauri
//!
//! The plan targeted Tauri v2. In practice, tao and wry — the two building blocks Tauri is
//! itself built on — suit *this* architecture better:
//!
//! - The frontend is not served by Tauri's asset protocol, it comes from a **remote HTTP
//!   origin** (`http://127.0.0.1:PORT`, served by aiohttp). Tauri v2 deliberately restricts its
//!   IPC for remote origins: one has to declare *capabilities* with a `remote` field, which is
//!   a permanent fight for an architecture where, by construction, everything already goes
//!   through the Python server.
//! - Tauri's bundler, updater and plugin system are of no use here: packaging is done by
//!   briefcase, which vendors this executable just as it already vendors ASTAP.
//!
//! What remains of Tauri is therefore exactly what is needed — its window and its webview —
//! without the configuration system that comes with it. Built by a bare `cargo build`, no CLI.
//! If a Tauri plugin ever becomes indispensable, the migration is mechanical: it is the same
//! stack underneath.
//!
//! # IPC channel
//!
//! `window.ipc.postMessage(json)` on the page side → [`handle_ipc`] on the native side. This is
//! the channel reserved for what the browser cannot do, and for **nothing else**:
//!
//! - native file dialogs (the HTML picker returns content, not a path);
//! - the **window chrome** — move, resize, minimize, maximize, close;
//! - the **system locale**, which the webview does not know: `navigator.language` returns that
//!   of the rendering engine, which follows Windows and not the user's choice within Retina.
//!
//! The last two points deserve justification, because they look like a breach of the
//! console-completeness pillar: they are not. That pillar covers **domain** actions — opening an
//! image, applying a process, arranging the panels — all of which must exist in the `app.*` API
//! and produce a Python echo. Moving an OS window is not a domain action; `app.*` has no reason
//! to expose it, and adding it there would bring nothing to a script. The locale falls into the
//! same category: it is a fact about the environment, not a Retina preference — that one lives
//! in `app.set_language`, on the server side, and takes precedence. Everything else goes
//! through the Python server, never through here.
//!
//! # Undecorated window
//!
//! The title bar is drawn by the frontend (menus + command center + layout toggles, VS Code
//! style), so the window is created with `with_decorations(false)`. Three consequences not to
//! undo:
//!
//! - `with_undecorated_shadow(true)` on Windows restores the drop shadow, snapping and the
//!   minimize animations; without it the window looks "flat" and loses Aero Snap.
//! - dragging and resizing become IPC commands.
//! - **the edges are not natively grabbable**: WebView2 creates child HWNDs that cover the whole
//!   client area, and `WM_NCHITTEST` never reaches the parent window. The frontend therefore
//!   lays down eight CSS handles that call back into `window_resize`
//!   (`web/src/shell/WindowResizeHandles.tsx`).
//!
//! Accepted losses: the Windows 11 Snap Layouts (which require returning `HTMAXBUTTON` from
//! `WM_NCHITTEST`, out of reach without patching tao), Alt+Space, and the "Move / Size" entry of
//! the taskbar right-click.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::ExitCode;
use std::rc::Rc;

use tao::{
    dpi::{LogicalSize, PhysicalSize},
    event::{Event, StartCause, WindowEvent},
    event_loop::{ControlFlow, EventLoopBuilder},
    window::{ResizeDirection, Theme, Window, WindowBuilder},
};
use wry::WebViewBuilder;

const DEFAULT_TITLE: &str = "Retina";
const DEFAULT_SIZE: (f64, f64) = (1600.0, 1000.0);
const MIN_SIZE: (f64, f64) = (960.0, 600.0);

/// Script injected before any page. Two corrections to browser behavior that has no place in a
/// desktop application.
const INIT_SCRIPT: &str = r#"
(() => {
  // Marker read by the frontend: it enables the full set of shortcuts (Ctrl+W, F12…),
  // which are impossible to capture in a browser tab.
  window.__RETINA_SHELL__ = true;

  // Bridge to the native dialogs. `postMessage` is one-way: requests are numbered and the
  // shell calls __retinaShellReply back with the same identifier.
  let nextId = 1;
  const waiting = new Map();
  window.__retinaShellReply = (id, result) => {
    const resolve = waiting.get(id);
    if (resolve) { waiting.delete(id); resolve(result); }
  };
  window.retinaShell = {
    invoke(cmd, args) {
      const id = nextId++;
      return new Promise((resolve) => {
        waiting.set(id, resolve);
        window.ipc.postMessage(JSON.stringify({ id, cmd, args: args || {} }));
      });
    },
  };

  // Ctrl+wheel zooms the page in a webview: in imaging software, it is the image zoom one
  // expects. It is neutralized here; the viewport handles the gesture.
  window.addEventListener('wheel', (e) => {
    if (e.ctrlKey) e.preventDefault();
  }, { passive: false });

  // Native webview context menu: replaced by the application's own.
  window.addEventListener('contextmenu', (e) => e.preventDefault());

  // Native → page direction, for what the page cannot observe: maximized state, focus.
  // The title bar needs it to choose between the "maximize" and "restore" glyphs.
  window.__retinaShellEvent = (name, detail) => {
    window.dispatchEvent(new CustomEvent('retina-shell-' + name, { detail }));
  };
})();
"#;

struct Args {
    url: String,
    title: String,
    /// Window icon (`.ico`). Supplied by `retina.web`, which knows where the package lives.
    icon: Option<String>,
}

fn parse_args() -> Result<Args, String> {
    let mut url: Option<String> = None;
    let mut title = DEFAULT_TITLE.to_string();
    let mut icon: Option<String> = None;
    let mut it = std::env::args().skip(1);

    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--title" => {
                title = it.next().ok_or("--title attend une valeur")?;
            }
            "--icon" => {
                icon = Some(it.next().ok_or("--icon expects a path")?);
            }
            "-h" | "--help" => {
                return Err("usage: retina_shell <url> [--title <title>] [--icon <file.ico>]".into());
            }
            other if other.starts_with("--") => {
                return Err(format!("unknown option: {other}"));
            }
            other => {
                if url.replace(other.to_string()).is_some() {
                    return Err("a single URL is expected".into());
                }
            }
        }
    }

    let url = url.ok_or("missing URL — usage: retina_shell <url> [--title <title>]")?;
    if !url.starts_with("http://127.0.0.1") && !url.starts_with("http://localhost") {
        // The shell only loads the local server. Without this guard, a tampered shortcut would
        // turn the application into a browser pointing anywhere, with the native IPC exposed to
        // the page.
        return Err(format!("URL refused (loopback only): {url}"));
    }
    Ok(Args { url, title, icon })
}

/// IPC request coming from the page, carried up to the event loop.
#[derive(Debug)]
enum UserEvent {
    Ipc(String),
}

/// Handles a request and sends the JSON result back to the page.
///
/// Returns `true` when the page asks to close: it is the caller that sets `ControlFlow::Exit`.
/// Definitely no `process::exit` here — that would cut the webview off without letting wry tear
/// its resources down.
///
/// The scope is strictly that of the module header: dialogs and window chrome. Opening a door
/// here to the file system or to the domain would create a capability reserved to the shell,
/// invisible from the console — exactly what parity forbids.
fn handle_ipc(window: &Window, webview: &wry::WebView, body: &str) -> bool {
    let request: serde_json::Value = match serde_json::from_str(body) {
        Ok(value) => value,
        Err(error) => {
            eprintln!("[shell] unreadable ipc: {error}");
            return false;
        }
    };
    let id = request.get("id").and_then(serde_json::Value::as_i64).unwrap_or(0);
    let cmd = request.get("cmd").and_then(serde_json::Value::as_str).unwrap_or("");
    let args = request.get("args").cloned().unwrap_or(serde_json::Value::Null);

    let mut quit = false;
    let result = match cmd {
        "open_file" => pick(&args, false),
        "open_files" => pick(&args, true),
        "open_folder" => pick_folder(&args),
        "save_file" => save(&args),
        // System locale, as the OS declares it ("fr-FR"). This is not a domain action — it is
        // environment, in the same way as "is the window maximized" — so there is no `app.*`
        // equivalent to invent: the frontend uses it only as a *starting guess*, and the server
        // remains the authority.
        "locale" => match sys_locale::get_locale() {
            Some(tag) => serde_json::Value::String(tag),
            None => serde_json::Value::Null,
        },
        // --- window chrome ---
        "window_drag" => {
            let _ = window.drag_window();
            serde_json::Value::Bool(true)
        }
        "window_resize" => {
            match args.get("direction").and_then(serde_json::Value::as_str).and_then(resize_dir) {
                Some(direction) => {
                    let _ = window.drag_resize_window(direction);
                    serde_json::Value::Bool(true)
                }
                None => serde_json::Value::Bool(false),
            }
        }
        "window_minimize" => {
            window.set_minimized(true);
            serde_json::Value::Bool(true)
        }
        "window_toggle_maximize" => {
            let maximized = !window.is_maximized();
            window.set_maximized(maximized);
            serde_json::Value::Bool(maximized)
        }
        "window_is_maximized" => serde_json::Value::Bool(window.is_maximized()),
        "window_close" => {
            quit = true;
            serde_json::Value::Bool(true)
        }
        other => {
            eprintln!("[shell] unknown command: {other}");
            serde_json::Value::Null
        }
    };

    let script = format!(
        "window.__retinaShellReply({id}, {})",
        serde_json::to_string(&result).unwrap_or_else(|_| "null".into())
    );
    if let Err(error) = webview.evaluate_script(&script) {
        eprintln!("[shell] reply failed: {error}");
    }
    quit
}

/// Compass points → tao resize direction (cf. `WindowResizeHandles.tsx`).
fn resize_dir(name: &str) -> Option<ResizeDirection> {
    Some(match name {
        "n" => ResizeDirection::North,
        "s" => ResizeDirection::South,
        "e" => ResizeDirection::East,
        "w" => ResizeDirection::West,
        "ne" => ResizeDirection::NorthEast,
        "nw" => ResizeDirection::NorthWest,
        "se" => ResizeDirection::SouthEast,
        "sw" => ResizeDirection::SouthWest,
        _ => return None,
    })
}

fn dialog(args: &serde_json::Value) -> rfd::FileDialog {
    let mut dialog = rfd::FileDialog::new();
    if let Some(title) = args.get("title").and_then(serde_json::Value::as_str) {
        dialog = dialog.set_title(title);
    }
    if let Some(directory) = args.get("directory").and_then(serde_json::Value::as_str) {
        dialog = dialog.set_directory(directory);
    }
    if let Some(filters) = args.get("filters").and_then(serde_json::Value::as_array) {
        for filter in filters {
            let name = filter.get("name").and_then(serde_json::Value::as_str).unwrap_or("Files");
            let extensions: Vec<&str> = filter
                .get("extensions")
                .and_then(serde_json::Value::as_array)
                .map(|list| list.iter().filter_map(serde_json::Value::as_str).collect())
                .unwrap_or_default();
            if !extensions.is_empty() {
                dialog = dialog.add_filter(name, &extensions);
            }
        }
    }
    dialog
}

fn pick(args: &serde_json::Value, multiple: bool) -> serde_json::Value {
    let dialog = dialog(args);
    if multiple {
        let paths = dialog
            .pick_files()
            .map(|list| list.iter().map(|p| p.to_string_lossy().to_string()).collect::<Vec<_>>())
            .unwrap_or_default();
        serde_json::json!(paths)
    } else {
        match dialog.pick_file() {
            Some(path) => serde_json::json!(path.to_string_lossy()),
            None => serde_json::Value::Null,
        }
    }
}

/// Pick a **directory** — what preprocessing asks for, since it starts from a directory of raw
/// frames.
///
/// Stays within the shell's scope: a path is returned, not content. Enumerating the directory is
/// the server's job (`pipeline.scan`), which is reachable from the console; doing it here would
/// create a capability the console would not have.
fn pick_folder(args: &serde_json::Value) -> serde_json::Value {
    match dialog(args).pick_folder() {
        Some(path) => serde_json::json!(path.to_string_lossy()),
        None => serde_json::Value::Null,
    }
}

fn save(args: &serde_json::Value) -> serde_json::Value {
    let mut dialog = dialog(args);
    if let Some(name) = args.get("filename").and_then(serde_json::Value::as_str) {
        dialog = dialog.set_file_name(name);
    }
    match dialog.save_file() {
        Some(path) => serde_json::json!(path.to_string_lossy()),
        None => serde_json::Value::Null,
    }
}

fn main() -> ExitCode {
    let args = match parse_args() {
        Ok(args) => args,
        Err(message) => {
            eprintln!("[shell] {message}");
            return ExitCode::FAILURE;
        }
    };

    if let Err(message) = run(args) {
        eprintln!("[shell] {message}");
        return ExitCode::FAILURE;
    }
    ExitCode::SUCCESS
}

/// Per-user profile directory for the webview.
///
/// `None` lets wry choose its default — acceptable as a last resort (development), never
/// desirable for an installed application. The path follows the platform convention for
/// application state: `%LOCALAPPDATA%` on Windows, `$XDG_DATA_HOME`/`~/.local/share` elsewhere.
fn profile_dir() -> Option<std::path::PathBuf> {
    let base = if cfg!(target_os = "windows") {
        std::env::var_os("LOCALAPPDATA").map(std::path::PathBuf::from)
    } else {
        std::env::var_os("XDG_DATA_HOME")
            .map(std::path::PathBuf::from)
            .or_else(|| {
                std::env::var_os("HOME").map(|home| std::path::PathBuf::from(home).join(".local/share"))
            })
    };
    let dir = base?.join("Retina").join("webview");
    // A creation failure is not fatal: wry will fall back on its default rather than refuse to
    // start.
    std::fs::create_dir_all(&dir).ok()?;
    Some(dir)
}

/// Loads the window icon. **Windows only**, and by design.
///
/// Portably, tao exposes only `Icon::from_rgba`, which assumes already decoded pixels: one would
/// have to add the `png` or `image` crate just for that. On Windows, the
/// `IconExtWindows::from_path` extension reads an `.ico` directly — zero dependencies.
/// Elsewhere, the window keeps the default icon: a known limitation, and inconsequential as long
/// as the packaged target is Windows.
#[cfg(target_os = "windows")]
fn window_icon(path: Option<&str>) -> Option<tao::window::Icon> {
    use tao::platform::windows::IconExtWindows;

    let path = path?;
    match tao::window::Icon::from_path(path, None) {
        Ok(icon) => Some(icon),
        Err(error) => {
            eprintln!("[shell] unreadable icon ({path}): {error}");
            None
        }
    }
}

/// Pushes a state event to the page (see `__retinaShellEvent` in `INIT_SCRIPT`).
fn notify_page(webview: &wry::WebView, detail: &str) {
    let script = format!("window.__retinaShellEvent&&window.__retinaShellEvent('window-state',{detail})");
    let _ = webview.evaluate_script(&script);
}

fn run(args: Args) -> Result<(), Box<dyn std::error::Error>> {
    // A loop with user events: wry's IPC handler has no access to the webview (it does not
    // exist yet when the handler is installed). The request is therefore routed through the
    // loop, which does hold both ends.
    let event_loop = EventLoopBuilder::<UserEvent>::with_user_event().build();
    let proxy = event_loop.create_proxy();

    // Default size clamped to the screen: on a 1536×864 laptop, a 1600×1000 window overflows
    // and is born partly off screen.
    let size = match event_loop.primary_monitor() {
        Some(monitor) => {
            let available: LogicalSize<f64> =
                PhysicalSize::new(monitor.size().width, monitor.size().height)
                    .to_logical(monitor.scale_factor());
            LogicalSize::new(
                DEFAULT_SIZE.0.min(available.width - 40.0).max(MIN_SIZE.0),
                DEFAULT_SIZE.1.min(available.height - 80.0).max(MIN_SIZE.1),
            )
        }
        None => LogicalSize::new(DEFAULT_SIZE.0, DEFAULT_SIZE.1),
    };

    let mut window_builder = WindowBuilder::new()
        .with_title(&args.title)
        .with_inner_size(size)
        .with_min_inner_size(LogicalSize::new(MIN_SIZE.0, MIN_SIZE.1))
        // The title bar is drawn by the frontend (cf. the module header).
        .with_decorations(false)
        // Still useful without decorations: `Theme::Dark` drives DWM dark mode, hence the color
        // of the drop shadow and of the window outline.
        .with_theme(Some(Theme::Dark));

    #[cfg(target_os = "windows")]
    {
        use tao::platform::windows::WindowBuilderExtWindows;
        // Gives an undecorated window back its shadow, Aero Snap and minimize animations.
        window_builder = window_builder.with_undecorated_shadow(true);
        if let Some(icon) = window_icon(args.icon.as_deref()) {
            window_builder = window_builder
                .with_window_icon(Some(icon.clone()))
                .with_taskbar_icon(Some(icon));
        }
    }
    #[cfg(not(target_os = "windows"))]
    let _ = &args.icon; // the icon is only set on Windows — cf. `window_icon`

    // `Rc` rather than a `move`: the loop's closure needs the window for the chrome, and the
    // webview needs a borrow at construction time.
    let window = Rc::new(window_builder.build(&event_loop)?);

    // By default WebView2 puts its profile (cache, IndexedDB, `lockfile`…) in
    // `<exe>.WebView2/`, **next to the executable**. That is untenable for an installed
    // application: under `C:\Program Files\` the directory is not writable, and the window would
    // refuse to open for a non-administrator user. Incidentally, those transient files appear
    // and disappear inside the build tree — enough to make WiX fail in the middle of building
    // the MSI (error WIX0083, experienced firsthand).
    // The profile is therefore sent where per-user state goes.
    let mut context = wry::WebContext::new(profile_dir());

    let builder = WebViewBuilder::new_with_web_context(&mut context)
        .with_url(&args.url)
        .with_initialization_script(INIT_SCRIPT)
        .with_ipc_handler(move |request| {
            let _ = proxy.send_event(UserEvent::Ipc(request.body().to_string()));
        })
        // The server is in the clear on the loopback interface: no remote content, hence
        // nothing to protect from mixed content, and the clipboard has to work (copying Python
        // code).
        .with_clipboard(true)
        .with_accept_first_mouse(true);

    // On Linux, `WebViewBuilder::build` takes wry's X11 path: it wraps a *foreign* X11 window
    // (`gdk_x11_window_foreign_new_for_display`) in a GtkWindow and mounts the webview inside
    // it. That arrangement renders a **black** window on NVIDIA drivers — the content composited
    // by GLX never reaches scan-out — and it additionally requires an Xlib handle (hence
    // `GDK_BACKEND=x11`, without which wry rejects with "window handle kind is not supported"
    // under Wayland). The webview is therefore placed directly into the native GTK container tao
    // has already created (`default_vbox`): that is wry's `new_gtk` path, which renders
    // correctly under X11 as well as under native Wayland. Verified on NVIDIA/Wayland (KDE).
    #[cfg(target_os = "linux")]
    let webview = {
        use tao::platform::unix::WindowExtUnix;
        use wry::WebViewBuilderExtUnix;
        let container = window
            .default_vbox()
            .expect("tao's GTK window should have a default vbox");
        builder.build_gtk(container)?
    };
    #[cfg(not(target_os = "linux"))]
    let webview = builder.build(&*window)?;
    let loop_window = Rc::clone(&window);
    let mut was_maximized = window.is_maximized();

    event_loop.run(move |event, _target, control_flow| {
        *control_flow = ControlFlow::Wait;
        match event {
            Event::NewEvents(StartCause::Init) => {
                eprintln!("[shell] window ready");
            }
            Event::UserEvent(UserEvent::Ipc(body)) => {
                if handle_ipc(&loop_window, &webview, &body) {
                    *control_flow = ControlFlow::Exit;
                }
            }
            Event::WindowEvent {
                event: WindowEvent::CloseRequested,
                ..
            } => {
                // Closing the window ends the process; on the Python side, `web.py` watches this
                // process and stops the server accordingly.
                *control_flow = ControlFlow::Exit;
            }
            // The title bar must alternate between the "maximize" and "restore" glyphs,
            // including when the user maximizes through Aero Snap rather than through the
            // button.
            Event::WindowEvent {
                event: WindowEvent::Resized(_),
                ..
            } => {
                let maximized = loop_window.is_maximized();
                if maximized != was_maximized {
                    was_maximized = maximized;
                    notify_page(&webview, &format!("{{maximized:{maximized}}}"));
                }
            }
            Event::WindowEvent {
                event: WindowEvent::Focused(focused),
                ..
            } => notify_page(&webview, &format!("{{focused:{focused}}}")),
            _ => {}
        }
    })
}
