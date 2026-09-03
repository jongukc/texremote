if vim.env.PAPERHERE_AGENT_PORT == nil or vim.env.PAPERHERE_TOKEN == nil then
  return
end

if vim.g.loaded_paperhere == 1 then
  return
end
vim.g.loaded_paperhere = 1

vim.g.vimtex_view_method = "paperhere"

local paperhere = require("paperhere")
paperhere.setup()

vim.api.nvim_create_user_command("PaperhereInverse", function(command)
  paperhere.inverse(command.args)
end, { nargs = 1 })
