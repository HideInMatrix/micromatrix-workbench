import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const here = path.dirname(fileURLToPath(import.meta.url))
const sourceRoot = path.resolve(here, '../src')
const maxVueLines = 400
const maxFunctionLines = 50

function sourceFiles(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const target = path.join(directory, entry.name)
    if (entry.isDirectory()) return sourceFiles(target)
    return /\.(?:ts|tsx|vue)$/.test(entry.name) && !entry.name.endsWith('.d.ts') ? [target] : []
  })
}

function lineCount(text) {
  return text.split(/\r?\n/).length
}

function vueScripts(text) {
  const scripts = []
  const pattern = /<script\b([^>]*)>([\s\S]*?)<\/script>/gi
  for (const match of text.matchAll(pattern)) {
    scripts.push({ attributes: match[1], source: match[2], offset: match.index ?? 0 })
  }
  return scripts
}

function functionBody(node) {
  if (
    ts.isFunctionDeclaration(node)
    || ts.isFunctionExpression(node)
    || ts.isArrowFunction(node)
    || ts.isMethodDeclaration(node)
    || ts.isConstructorDeclaration(node)
    || ts.isGetAccessorDeclaration(node)
    || ts.isSetAccessorDeclaration(node)
  ) return node.body
  return undefined
}

function functionName(node) {
  if ('name' in node && node.name && ts.isIdentifier(node.name)) return node.name.text
  if (ts.isArrowFunction(node) || ts.isFunctionExpression(node)) {
    const parent = node.parent
    if (ts.isVariableDeclaration(parent) && ts.isIdentifier(parent.name)) return parent.name.text
    if (ts.isPropertyAssignment(parent)) return parent.name.getText()
  }
  return '<anonymous>'
}

function inspectFunctions(file, sourceText, baseLine, failures) {
  const source = ts.createSourceFile(file, sourceText, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
  const visit = node => {
    if (ts.isClassDeclaration(node) || ts.isClassExpression(node)) {
      const line = source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1 + baseLine
      failures.push(`${file}:${line} frontend business code must not use class syntax`)
    }
    const body = functionBody(node)
    if (body) {
      const start = source.getLineAndCharacterOfPosition(body.getStart(source)).line + 1 + baseLine
      const end = source.getLineAndCharacterOfPosition(body.getEnd()).line + 1 + baseLine
      const lines = end - start + 1
      if (lines > maxFunctionLines) failures.push(`${file}:${start} ${functionName(node)}() = ${lines} lines`)
    }
    ts.forEachChild(node, visit)
  }
  visit(source)
}

function inspectVue(file, text, failures) {
  const lines = lineCount(text)
  if (lines > maxVueLines) failures.push(`${file}: Vue component = ${lines} lines`)
  const scripts = vueScripts(text)
  if (!scripts.some(item => /\bsetup\b/.test(item.attributes))) {
    failures.push(`${file}: Vue component must use <script setup lang="ts">`)
  }
  for (const script of scripts) {
    const baseLine = text.slice(0, script.offset).split(/\r?\n/).length
    inspectFunctions(file, script.source, baseLine, failures)
  }
}

function inspectSource(file, failures) {
  const text = fs.readFileSync(file, 'utf8')
  const relative = path.relative(path.resolve(here, '..'), file)
  if (file.endsWith('.vue')) inspectVue(relative, text, failures)
  else inspectFunctions(relative, text, 0, failures)
}

function main() {
  const failures = []
  for (const file of sourceFiles(sourceRoot)) inspectSource(file, failures)
  if (failures.length) {
    console.error('Frontend code standards failed:')
    for (const failure of failures) console.error(`- ${failure}`)
    process.exitCode = 1
    return
  }
  console.log(`Frontend code standards passed: Vue <= ${maxVueLines} lines, functions <= ${maxFunctionLines} lines.`)
}

main()
