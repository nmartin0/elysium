// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { isShared, moduleConfig, packageOf, privateCopyOfShared } from './moduleBuild'

const LIBRARIES = ['react', 'react/jsx-runtime', '@blueprintjs/core', 'echarts/core']
const PACKAGES = ['@elysium/shell-api']

describe('isShared', () => {
  it('leaves the shared libraries and every entry of a shared package bare', () => {
    expect(isShared('react', LIBRARIES, PACKAGES)).toBe(true)
    expect(isShared('react/jsx-runtime', LIBRARIES, PACKAGES)).toBe(true)
    expect(isShared('@elysium/shell-api/components/DataTable', LIBRARIES, PACKAGES)).toBe(true)
    expect(isShared('@dagrejs/dagre', LIBRARIES, PACKAGES)).toBe(false)
  })
})

describe('privateCopyOfShared', () => {
  it('names the shared package a deep import would copy', () => {
    expect(privateCopyOfShared('@blueprintjs/core/lib/esm/components', LIBRARIES, PACKAGES)).toBe('@blueprintjs/core')
    expect(privateCopyOfShared('echarts/lib/chart/bar', LIBRARIES, PACKAGES)).toBe('echarts')
    expect(privateCopyOfShared('react/cjs/react.production.js', LIBRARIES, PACKAGES)).toBe('react')
  })

  it('lets a shared entry, and a library nobody shares, through', () => {
    expect(privateCopyOfShared('react/jsx-runtime', LIBRARIES, PACKAGES)).toBeUndefined()
    expect(privateCopyOfShared('@dagrejs/dagre', LIBRARIES, PACKAGES)).toBeUndefined()
    expect(privateCopyOfShared('./SchemaPanel', LIBRARIES, PACKAGES)).toBeUndefined()
  })
})

describe('packageOf', () => {
  it('reads scoped and plain package names', () => {
    expect(packageOf('@a/b/c')).toBe('@a/b')
    expect(packageOf('react/jsx-runtime')).toBe('react')
  })
})

describe('moduleConfig', () => {
  it('builds one ES module and its stylesheet, leaving shared imports bare', () => {
    const config = moduleConfig({ root: '/m', entry: 'src/module.tsx', libraries: LIBRARIES, packages: PACKAGES })
    const lib = config.build?.lib
    const external = config.build?.rolldownOptions?.external as (id: string) => boolean

    expect(lib && lib.formats).toEqual(['es'])
    expect(lib && lib.cssFileName).toBe('index')
    expect(external('react')).toBe(true)
    expect(external('@dagrejs/dagre')).toBe(false)
  })
})
