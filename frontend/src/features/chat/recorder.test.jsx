import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MAX_RECORD_SECONDS, useVoiceRecorder } from './useVoiceRecorder'

class FakeRecorder {
  static instances = []
  static isTypeSupported = (t) => t === 'audio/webm;codecs=opus'
  constructor(stream, opts) { this.stream = stream; this.opts = opts; this.state = 'inactive'; FakeRecorder.instances.push(this) }
  start() { this.state = 'recording' }
  pause() { this.state = 'paused' }
  resume() { this.state = 'recording' }
  stop() { if (this.state === 'inactive') return; this.state = 'inactive'; if (this.empty !== true) this.ondataavailable?.({ data: new Blob(['audio-bytes'], { type: 'audio/webm' }) }); this.onstop?.() }
}
const track = () => ({ stop: vi.fn() })
let tracks

beforeEach(() => {
  vi.useFakeTimers()
  FakeRecorder.instances = []
  tracks = [track()]
  globalThis.MediaRecorder = FakeRecorder
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia: vi.fn(async () => ({ getTracks: () => tracks })) } })
  URL.createObjectURL = vi.fn(() => 'blob:rec'); URL.revokeObjectURL = vi.fn()
})
afterEach(() => { vi.useRealTimers(); delete globalThis.MediaRecorder })

const start = async (hook) => { await act(async () => { await hook.result.current.start() }) }

describe('useVoiceRecorder', () => {
  it('records, shows the elapsed time, and ends in a preview holding the real audio file', async () => {
    const hook = renderHook(() => useVoiceRecorder())
    expect(hook.result.current.supported).toBe(true)
    await start(hook)
    expect(hook.result.current.state).toBe('recording')
    await act(async () => { vi.advanceTimersByTime(3200) })
    expect(hook.result.current.seconds).toBeGreaterThanOrEqual(3)
    act(() => hook.result.current.stop())
    expect(hook.result.current.state).toBe('preview')
    const { file, seconds, url } = hook.result.current.result
    expect(file.name).toBe('recording.webm'); expect(file.type).toBe('audio/webm'); expect(file.size).toBeGreaterThan(0); expect(seconds).toBeGreaterThanOrEqual(3); expect(url).toBe('blob:rec')
    expect(tracks[0].stop).toHaveBeenCalled()                                    // the microphone is released as soon as recording stops
  })
  it('pauses and resumes without counting the paused time', async () => {
    const hook = renderHook(() => useVoiceRecorder())
    await start(hook)
    await act(async () => { vi.advanceTimersByTime(2000) })
    act(() => hook.result.current.pause()); expect(hook.result.current.state).toBe('paused'); expect(FakeRecorder.instances[0].state).toBe('paused')
    await act(async () => { vi.advanceTimersByTime(10000) })
    act(() => hook.result.current.resume()); expect(hook.result.current.state).toBe('recording')
    await act(async () => { vi.advanceTimersByTime(1000) })
    act(() => hook.result.current.stop())
    expect(hook.result.current.result.seconds).toBeLessThanOrEqual(4)             // about 3 s recorded, not 13
  })
  it('discarding a preview or a recording throws it away, frees the URL and the microphone', async () => {
    const hook = renderHook(() => useVoiceRecorder())
    await start(hook); act(() => hook.result.current.stop())
    act(() => hook.result.current.discard())
    expect(hook.result.current.state).toBe('idle'); expect(hook.result.current.result).toBeNull(); expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:rec')
    await start(hook); act(() => hook.result.current.discard())
    expect(hook.result.current.state).toBe('idle'); expect(hook.result.current.result).toBeNull(); expect(tracks[0].stop).toHaveBeenCalled()
  })
  it('explains a blocked microphone, a missing one, and a browser that cannot record', async () => {
    const hook = renderHook(() => useVoiceRecorder())
    navigator.mediaDevices.getUserMedia.mockRejectedValueOnce(Object.assign(new Error('x'), { name: 'NotAllowedError' }))
    await start(hook); expect(hook.result.current.error).toMatch(/Microphone access was blocked/); expect(hook.result.current.state).toBe('idle')
    navigator.mediaDevices.getUserMedia.mockRejectedValueOnce(Object.assign(new Error('x'), { name: 'NotFoundError' }))
    await start(hook); expect(hook.result.current.error).toMatch(/No microphone was found/)
    delete globalThis.MediaRecorder
    const none = renderHook(() => useVoiceRecorder()); expect(none.result.current.supported).toBe(false)
    await start(none); expect(none.result.current.error).toMatch(/not supported/)
  })
  it('reports an empty recording instead of offering to send nothing', async () => {
    const hook = renderHook(() => useVoiceRecorder())
    await start(hook)
    FakeRecorder.instances[0].empty = true
    act(() => hook.result.current.stop())
    expect(hook.result.current.state).toBe('idle'); expect(hook.result.current.error).toMatch(/Nothing was recorded/); expect(hook.result.current.result).toBeNull()
  })
  it('stops by itself at the maximum length and opens the preview', async () => {
    const hook = renderHook(() => useVoiceRecorder())
    await start(hook)
    await act(async () => { vi.advanceTimersByTime((MAX_RECORD_SECONDS + 1) * 1000) })
    expect(hook.result.current.state).toBe('preview')
    expect(hook.result.current.result.seconds).toBeGreaterThanOrEqual(MAX_RECORD_SECONDS)
  })
  it('releases the recorder and the microphone when the component goes away mid-recording', async () => {
    const hook = renderHook(() => useVoiceRecorder())
    await start(hook)
    hook.unmount()
    expect(FakeRecorder.instances[0].state).toBe('inactive'); expect(tracks[0].stop).toHaveBeenCalled()
  })
})
