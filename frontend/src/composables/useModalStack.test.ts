import { afterEach, describe, expect, it } from 'vitest'
import { isTopmostModal, popModal, pushModal } from './useModalStack'

// The stack is module-scoped (one document, one stack), so every test must
// pop what it pushed — tracked ids + afterEach keep tests order-independent.
const pushed: symbol[] = []
function push(label: string): symbol {
  const id = Symbol(label)
  pushModal(id)
  pushed.push(id)
  return id
}

afterEach(() => {
  while (pushed.length) popModal(pushed.pop()!)
})

describe('useModalStack', () => {
  it('reports nothing as topmost when the stack is empty', () => {
    expect(isTopmostModal(Symbol('ghost'))).toBe(false)
  })

  it('treats the last pushed modal as topmost (LIFO)', () => {
    const outer = push('outer')
    expect(isTopmostModal(outer)).toBe(true)

    const inner = push('inner')
    expect(isTopmostModal(inner)).toBe(true)
    expect(isTopmostModal(outer)).toBe(false)
  })

  it('restores the outer modal as topmost when the inner one pops', () => {
    const outer = push('outer')
    const inner = push('inner')

    popModal(inner)
    expect(isTopmostModal(outer)).toBe(true)
    expect(isTopmostModal(inner)).toBe(false)
  })

  it('ignores duplicate pushes of the same id', () => {
    const a = push('a')
    pushModal(a) // second push must not create a second stack entry
    const b = push('b')

    popModal(b)
    expect(isTopmostModal(a)).toBe(true)
    popModal(a)
    expect(isTopmostModal(a)).toBe(false)
  })

  it('tolerates popping an id that was never pushed', () => {
    const a = push('a')
    popModal(Symbol('never-pushed'))
    expect(isTopmostModal(a)).toBe(true)
  })
})
