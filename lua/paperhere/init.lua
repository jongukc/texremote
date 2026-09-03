local M = {}

local uv = vim.uv or vim.loop
local host = vim.env.PAPERHERE_AGENT_HOST or "127.0.0.1"
local port = tonumber(vim.env.PAPERHERE_AGENT_PORT)
local token = vim.env.PAPERHERE_TOKEN
local root = vim.env.PAPERHERE_ROOT or vim.fn.getcwd()
local configured_pdf = vim.env.PAPERHERE_PDF
local build_command = vim.env.PAPERHERE_BUILD_COMMAND
local auto_build = vim.env.PAPERHERE_AUTO_BUILD ~= "0"

local build_running = false
local build_pending = false
local build_started = false
local last_error = nil

local function report_error(message)
  if message == last_error then
    return
  end
  last_error = message
  vim.schedule(function()
    vim.notify("paperhere: " .. message, vim.log.levels.ERROR)
  end)
end

local function post(payload)
  if not port or not token then
    return
  end
  local body = vim.json.encode(payload)
  local request = table.concat({
    "POST /api/event HTTP/1.1",
    "Host: " .. host,
    "Authorization: Bearer " .. token,
    "Content-Type: application/json",
    "Content-Length: " .. #body,
    "Connection: close",
    "",
    body,
  }, "\r\n")
  local client = uv.new_tcp()
  client:connect(host, port, function(connect_error)
    if connect_error then
      client:close()
      report_error("preview server connection failed: " .. connect_error)
      return
    end
    client:read_start(function(read_error, data)
      if read_error then
        report_error("preview server response failed: " .. read_error)
      end
      if data == nil and not client:is_closing() then
        client:close()
      end
    end)
    client:write(request, function(write_error)
      if write_error then
        report_error("preview update failed: " .. write_error)
        if not client:is_closing() then
          client:close()
        end
        return
      end
      client:shutdown()
    end)
  end)
end

function M.view(data)
  post({
    type = "view",
    pdf = data.pdf,
    tex = data.tex,
    line = data.line,
    column = data.column,
  })
end

function M.build(pdf)
  post({ type = "build", pdf = pdf })
end

local function shell_command(command)
  local parts = { vim.o.shell }
  vim.list_extend(parts, vim.split(vim.o.shellcmdflag, "%s+", { trimempty = true }))
  table.insert(parts, command)
  return parts
end

local function start_custom_build()
  if not build_command or build_command == "" then
    return
  end
  if build_running then
    build_pending = true
    return
  end
  build_running = true
  build_pending = false
  vim.system(shell_command(build_command), { cwd = root, text = true }, function(result)
    build_running = false
    if result.code == 0 then
      if configured_pdf and configured_pdf ~= "" then
        M.build(configured_pdf)
      end
    else
      local detail = vim.trim(result.stderr or result.stdout or "build failed")
      report_error("build failed: " .. detail)
    end
    if build_pending then
      start_custom_build()
    end
  end)
end

local function decode_hex(value)
  if #value % 2 ~= 0 or value:find("[^0-9a-fA-F]") then
    error("invalid inverse-search payload")
  end
  return (value:gsub("..", function(pair)
    return string.char(tonumber(pair, 16))
  end))
end

function M.inverse(encoded)
  local ok, data = pcall(function()
    return vim.json.decode(decode_hex(encoded))
  end)
  if not ok or type(data) ~= "table" then
    report_error("invalid inverse-search request")
    return
  end
  local handled = false
  if vim.fn.exists("*vimtex#view#inverse_search") == 1 then
    local success, result = pcall(
      vim.fn["vimtex#view#inverse_search"],
      data.line,
      data.path,
      data.column or 0
    )
    handled = success and type(result) == "number" and result >= 0
  end
  if not handled then
    local success, error_message = pcall(vim.api.nvim_cmd, {
      cmd = "edit",
      args = { data.path },
    }, {})
    if not success then
      report_error("cannot open source: " .. error_message)
      return
    end
    pcall(vim.api.nvim_win_set_cursor, 0, { math.max(1, data.line), math.max(0, data.column or 0) })
  end
end

function M.setup()
  local group = vim.api.nvim_create_augroup("paperhere", { clear = true })
  vim.api.nvim_create_autocmd("User", {
    group = group,
    pattern = "VimtexEventInitPost",
    callback = function()
      if build_started or not auto_build then
        return
      end
      build_started = true
      if build_command and build_command ~= "" then
        start_custom_build()
      else
        vim.schedule(function()
          vim.cmd("silent! VimtexCompile!")
        end)
      end
    end,
  })
  if build_command and build_command ~= "" then
    vim.api.nvim_create_autocmd("BufWritePost", {
      group = group,
      pattern = { "*.tex", "*.bib", "*.sty", "*.cls" },
      callback = start_custom_build,
    })
  end
end

return M
