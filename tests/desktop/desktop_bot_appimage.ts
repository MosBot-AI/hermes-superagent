/** Launch a verified source build or the matching bundled AppImage. */
import * as fs from 'node:fs'
import * as path from 'node:path'

import { _electron, expect } from '@playwright/test'

import { launchCoreApp } from './harness'

export async function launchBotDesktop(env: Record<string, string>) {
  const work = process.env.HERMES_E2E_APPIMAGE_WORK
  if (!work) return launchCoreApp(env)

  const root = path.join(work, 'squashfs-root')
  const resources = path.join(root, 'resources')
  const expectedCommit = process.env.HERMES_E2E_PACKAGED_COMMIT
  expect(expectedCommit).toMatch(/^[0-9a-f]{40}$/)
  const stamp = JSON.parse(fs.readFileSync(path.join(resources, 'install-stamp.json'), 'utf8'))
  expect(stamp).toMatchObject({
    commit: expectedCommit,
    dirty: false,
    source: 'commit-build',
    payload: 'bundled',
    distribution: 'desktop-app',
    runtime: { commands: { hermes: expect.any(String) } }
  })
  const executablePath = path.join(root, 'AppRun')
  fs.accessSync(executablePath, fs.constants.X_OK)
  const payload = path.join(resources, 'agent-payload')
  const launcher = path.resolve(payload, stamp.runtime.commands.hermes)
  expect(launcher.startsWith(payload + path.sep)).toBe(true)
  fs.accessSync(launcher, fs.constants.X_OK)
  const packagedEnv = { ...env }
  delete packagedEnv.HERMES_DESKTOP_HERMES_ROOT
  delete packagedEnv.HERMES_DESKTOP_PYTHON
  const app = await _electron.launch({
    executablePath,
    args: ['--disable-gpu', '--no-sandbox'],
    env: packagedEnv,
    cwd: root
  })
  try {
    const identity = await app.evaluate(({ app }) => ({
      packaged: app.isPackaged,
      executable: process.execPath,
      resources: process.resourcesPath,
      appPath: app.getAppPath()
    }))
    expect(path.dirname(identity.executable)).toBe(root)
    expect(identity.executable).not.toBe(executablePath)
    expect(identity).toMatchObject({
      packaged: true,
      resources,
      appPath: path.join(resources, 'app.asar')
    })
    return { app, page: await app.firstWindow() }
  } catch (error) {
    await app.close().catch(() => undefined)
    throw error
  }
}
