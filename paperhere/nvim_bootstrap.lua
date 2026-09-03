local config = vim.fn.stdpath("config")
local user_init_lua = config .. "/init.lua"
local user_init_vim = config .. "/init.vim"
local agent_port = vim.env.PAPERHERE_AGENT_PORT
local token = vim.env.PAPERHERE_TOKEN

-- Keep a separately installed paperhere.nvim dormant while the user's config
-- loads. The launcher must use the runtime bundled with its own protocol.
vim.env.PAPERHERE_AGENT_PORT = nil
vim.env.PAPERHERE_TOKEN = nil

if vim.fn.filereadable(user_init_lua) == 1 then
  vim.env.MYVIMRC = user_init_lua
  local ok, error_message = pcall(dofile, user_init_lua)
  if not ok then
    vim.api.nvim_echo({ { error_message, "ErrorMsg" } }, true, {})
  end
elseif vim.fn.filereadable(user_init_vim) == 1 then
  vim.env.MYVIMRC = user_init_vim
  local ok, error_message = pcall(vim.cmd.source, vim.fn.fnameescape(user_init_vim))
  if not ok then
    vim.api.nvim_echo({ { error_message, "ErrorMsg" } }, true, {})
  end
end

vim.env.PAPERHERE_AGENT_PORT = agent_port
vim.env.PAPERHERE_TOKEN = token

local runtime = vim.env.PAPERHERE_NVIM_RUNTIME
if not runtime or runtime == "" then
  error("PAPERHERE_NVIM_RUNTIME is not set")
end

vim.opt.runtimepath:prepend(runtime)
vim.g.vimtex_view_method = "paperhere"
dofile(runtime .. "/plugin/paperhere.lua")
