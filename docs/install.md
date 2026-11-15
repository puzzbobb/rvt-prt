# Installing

Releases built by the release workflow come with prebuilt packages for Linux (x86_64, aarch64)
and macOS (Apple silicon, Intel), which need no Rust toolchain:

```bash
python3 -m venv .venv
.venv/bin/pip install rvt-prt
```

Where there is no prebuilt package for a release or a platform, pip compiles it from source,
which needs the tools below. To work on rvt-prt, or to run the latest code, install from a
clone as described here.

rvt-prt is installed from a clone of its repository. One
part of it is **compiled on your machine** the first time you install: the native extension
`rvt_prt._native`, which wraps [rvt-rs](https://github.com/DrunkOnJava/rvt-rs), a Rust library
that cargo downloads from crates.io during the build (the `rvt` crate). Expect a few minutes: about 5 on a small ARM board (4 cores,
8 GB), less on a desktop.

It is developed and tested on 64-bit ARM Linux (Debian-based). macOS should work the same way but
is untested. Windows is untested, and sheets print one at a time there, without the memory guard
(see [Limitations](limitations.md#platforms)).

## What you need

| | |
|---|---|
| Python | 3.10 or newer, with `venv` |
| git | to clone the repository |
| Rust | 1.87 or newer, from [rustup](https://rustup.rs). Needed only to compile |
| C toolchain | the linker Rust needs (`build-essential` on Debian, the Xcode command-line tools on macOS) |
| Memory | 4 GB works, 8 GB is recommended. See [Performance and memory](performance.md#memory) |
| Network | while compiling: cargo downloads rvt-rs and the other Rust libraries from crates.io |
| Disk | About 1.5 GB while compiling: the Rust toolchain (about 750 MB, in your home folder) and the build (about 550 MB in `native/target`). Both can be removed afterwards. Then about 200 MB for the Python libraries, plus the caches that prints build (hundreds of MB for a large model with links) |

## 1. Install the tools

**Debian, Ubuntu and their relatives:**

```bash
sudo apt update
sudo apt install -y git python3 python3-venv build-essential curl
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
. "$HOME/.cargo/env"          # or open a new terminal
rustc --version               # 1.87 or newer
```

**macOS:** `xcode-select --install` for the C toolchain, Python 3 from python.org or Homebrew,
then the same `curl ... sh.rustup.rs` line and `. "$HOME/.cargo/env"`.

**Windows (untested):** Python from python.org, Git for Windows, Visual Studio Build Tools with
"Desktop development with C++", and `rustup-init.exe` from [rustup.rs](https://rustup.rs).

## 2. Fonts

A `.rvt` names its fonts but holds none. rvt-prt draws text with font files it finds on your
machine, and falls back to free substitutes with the same character widths. Most Revit text is
Arial. On Debian and its relatives, either of these gives a good result:

```bash
sudo apt install fonts-liberation          # Liberation Sans: free, the same widths as Arial
sudo apt install ttf-mscorefonts-installer # Arial itself (Debian's contrib section)
sudo apt install fonts-noto-cjk            # Japanese, Chinese and Korean text
```

With none of them installed, text still prints, in PyMuPDF's built-in fonts. The details are in
[Fonts, linked models and caches](configuration.md#fonts).

## 3. Clone and compile

```bash
git clone https://github.com/puzzbobb/rvt-prt.git
cd rvt-prt
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e .          # compiles rvt-rs and the extension, then installs `rvt-prt`
```

`pip install -e .` fetches the build tool (maturin), compiles rvt-rs and the extension in release
mode into `native/target`, and puts the result, `src/rvt_prt/_native.abi3.so` (about 6 MB),
beside the Python code. Nothing seems to happen for a long time while Rust compiles. That is
normal. To see the compiler's progress, add `-v`.

Check that it worked:

```bash
.venv/bin/python -c "import rvt_prt._native; print('ok')"
.venv/bin/rvt-prt --version
```

Optional extras:

```bash
.venv/bin/pip install -e ".[dxf]"   # DXF export, and reading Revit's DXF exports (ezdxf)
.venv/bin/pip install -e ".[dev]"   # the above, plus pytest, ruff, mypy and maturin
```

## 4. Print something

```bash
.venv/bin/rvt-prt list model.rvt                    # the sheets and their views
.venv/bin/rvt-prt print model.rvt -o sheets         # every sheet, each to its own PDF in sheets/
.venv/bin/rvt-prt print model.rvt -o sheets.pdf     # every sheet in one PDF
```

The first print of a model is the slow one. It meshes the model and each linked model and builds
its caches, which takes minutes for a large model with links. The progress lines say which stage
it is in. Later prints of the same model reuse the caches. [Command line](usage.md) has the rest.

## Updating

```bash
git pull
.venv/bin/pip install -e .          # recompiles the extension (and a moved rvt-rs pin)
```

Changes to the Rust side are not picked up without the last line. An update that changes a
decoder rebuilds that decoder's caches on the next print, which is slow once.

## Saving disk space after compiling

- `native/target` (about 550 MB) only makes recompiling faster. Remove it with
  `cargo clean --manifest-path native/Cargo.toml`. The next `pip install -e .` then compiles
  everything again.
- The Rust toolchain (about 750 MB in `~/.rustup` and `~/.cargo`) is needed only to compile.
  `rustup self uninstall` removes it. Install it again (step 1) before updating.

## If the install fails

| What you see | What to do |
|---|---|
| cargo cannot download `rvt` or another crate | The build needs crates.io. Check the network or proxy (cargo reads `HTTPS_PROXY`); after one successful build the crates are cached in `~/.cargo/registry` |
| `native/rvt-rs` is left over from an older clone | rvt-rs was a git submodule before; the folder is no longer used. Run `git submodule deinit -f native/rvt-rs` and delete the folder |
| `cargo` or `rustc` not found, or "linker `cc` not found" | Install Rust and the C toolchain (step 1), open a new terminal, and install again |
| The compile is killed, or the machine freezes while compiling (4 GB machines) | Compile with one job at a time: `CARGO_BUILD_JOBS=1 .venv/bin/pip install -e .`, and close other programs |
| Prints are very slow after building by hand | Build with `--release` (`maturin develop --release`). A debug build is 10 to 50 times slower |

## About rvt-rs

rvt-rs is a separate project, used as published. `native/Cargo.toml` pins one release of its
`rvt` crate on crates.io (`rvt = "=0.24.0"`), unpatched, and `native/Cargo.lock` the versions of
everything it needs. Changes to rvt-rs go to rvt-rs itself.
The integration lives in this repository, in `native/src/`.
