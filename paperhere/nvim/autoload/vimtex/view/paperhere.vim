function! vimtex#view#paperhere#new() abort
  return s:viewer.init()
endfunction

let s:viewer = vimtex#view#_template#new({
      \ 'name': 'Paperhere',
      \})

function! s:viewer._check() dict abort
  return luaeval("require('paperhere') ~= nil")
endfunction

function! s:viewer._exists() dict abort
  return v:true
endfunction

function! s:viewer.out() dict abort
  if !empty($PAPERHERE_PDF)
    return fnamemodify($PAPERHERE_PDF, ':p')
  endif
  return exists('*b:vimtex.compiler.get_file')
        \ ? b:vimtex.compiler.get_file('pdf')
        \ : ''
endfunction

function! s:notify_view(outfile) abort
  call luaeval("require('paperhere').view(_A)", {
        \ 'pdf': fnamemodify(a:outfile, ':p'),
        \ 'tex': expand('%:p'),
        \ 'line': line('.'),
        \ 'column': col('.'),
        \})
endfunction

function! s:viewer._start(outfile) dict abort
  call s:notify_view(a:outfile)
endfunction

function! s:viewer._forward_search(outfile) dict abort
  call s:notify_view(a:outfile)
endfunction

function! s:viewer.compiler_callback(outfile) dict abort
  call luaeval("require('paperhere').build(_A)", fnamemodify(a:outfile, ':p'))
endfunction
