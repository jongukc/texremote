# paperhere.nvim

Neovim integration for [Paperhere](https://github.com/jongukc/paperhere). It connects VimTeX to Paperhere's live browser PDF viewer for forward and inverse SyncTeX.

The main `paperhere open` command loads this runtime automatically. To install the integration independently with lazy.nvim:

```lua
{
  "jongukc/paperhere",
  branch = "nvim",
  name = "paperhere.nvim",
  lazy = false,
  dependencies = { "lervag/vimtex" },
}
```

For local Paperhere development, load the nested source directly:

```lua
{
  dir = "~/code/paperhere/paperhere/nvim",
  name = "paperhere.nvim",
  lazy = false,
}
```

The plugin is dormant outside a session started by Paperhere. Inside a session it selects the `paperhere` VimTeX viewer, relays `:VimtexView` to the browser, receives inverse-search jumps, and reports successful builds for automatic PDF refresh.

The `nvim` branch is generated from this directory. Do not edit it directly.
