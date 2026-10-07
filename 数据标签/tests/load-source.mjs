import fs from 'node:fs/promises'
import ts from 'typescript'

const compiled = new Map()
async function moduleURL(sourceURL) {
  if (compiled.has(sourceURL.href)) return compiled.get(sourceURL.href)
  const promise = compileSource(sourceURL)
  compiled.set(sourceURL.href, promise)
  return promise
}

async function compileSource(sourceURL) {
  const source = await fs.readFile(sourceURL, 'utf8')
  let output = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX },
  }).outputText
  for (const [statement, specifier] of output.matchAll(/from ['"]([^'"]+)['"]/g)) {
    let target
    if (specifier.startsWith('.')) {
      for (const suffix of ['', '.ts', '.tsx']) {
        const candidate = new URL(specifier + suffix, sourceURL)
        try { await fs.access(candidate); target = await moduleURL(candidate); break }
        catch (error) { if (error.code !== 'ENOENT') throw error }
      }
      if (!target) throw new Error('Cannot resolve ' + specifier + ' from ' + sourceURL.href)
    } else target = import.meta.resolve(specifier)
    output = output.replace(statement, `from ${JSON.stringify(target)}`)
  }
  return 'data:text/javascript;base64,' + Buffer.from(output).toString('base64')
}

// Compile the actual TypeScript helpers and component imports in memory.
export async function loadSource(relativePath) {
  return import(await moduleURL(new URL('../' + relativePath, import.meta.url)))
}
