"""Replay Pi events through the extension and real Python hooks, with isolated OS I/O."""
import subprocess
import textwrap
import unittest

from helpers import REPO_ROOT, hook_test_env


BOOTSTRAP = r"""
import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';
import { EventEmitter } from 'node:events';
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

// Replace only the subprocess boundary: keep real hook payloads and Python behavior,
// but preserve the test's isolated state paths rather than production /tmp paths.
const runner = `
import { spawnSync } from 'node:child_process';
export const FAST_HOOK_TIMEOUT_MS=100, HOOK_TIMEOUT_MS=100,
 SESSION_HOOK_TIMEOUT_MS=100, TABTITLE_BARRIER_MS=100;
export const runnerLog = () => {};
export const waitBriefly = p => p;
export async function runHook(script, payload) {
 if (script === 'tab-stop-question-hook.py' && globalThis.stopHookGate) {
  globalThis.stopHookStarted = true;
  await globalThis.stopHookGate;
 }
 const result = spawnSync('python3', ['hooks/' + script], {
  input: JSON.stringify(payload), encoding:'utf8', env:process.env,
 });
 if (result.status !== 0) throw new Error(result.stderr);
 return 'ok';
}`;
registerHooks({
 resolve(specifier, context, next) {
  if (specifier === './hook-runner.js') return {url:'data:text/javascript,' + encodeURIComponent(runner), shortCircuit:true};
  if (specifier.startsWith('./') && specifier.endsWith('.js')) specifier = specifier.slice(0,-3) + '.ts';
  return next(specifier, context);
 }
});
Object.defineProperty(process.stdin, 'isTTY', {value:true});
Object.defineProperty(process.stdout, 'isTTY', {value:true});
process.env.TERM_PROGRAM = 'ghostty';
delete process.env.PI_SUBAGENT_CHILD;
delete process.env._CLAUDE_HOOK_NESTED;
const {default: extension} = await import('./pi-extension/index.ts');
const handlers = new Map();
const events = new EventEmitter();
const pi = {events: {
 on: (name, handler) => { events.on(name, handler); return () => events.off(name, handler); },
 emit: (name, data) => events.emit(name, data),
}, on: (name, handler) => handlers.set(name, handler)};
let idle = true;
const ctx = {hasUI:true, cwd:process.cwd(), isIdle:()=>idle, sessionManager:{
 getSessionId:()=> 'wait-test', getSessionFile:()=>undefined,
}};
const id = `${process.pid}-wait-test`;
const titlePath = join(process.env.GHOSTTY_PEON_DEBOUNCE_DIR, id);
const seed = (emoji='🌀') => writeFileSync(titlePath, '123\n' + emoji + ' fix-waits');
const title = () => readFileSync(titlePath, 'utf8').split('\n')[1];
writeFileSync(join(process.env.GHOSTTY_PEON_TERMINAL_ID_DIR, id), 'term-test-1');
seed();
extension(pi);
const emit = async (name, event={}) => {
 await handlers.get(name)?.(event, ctx);
 // Bus handlers are notification-only; drain their promise queue.
 for (let n=0;n<20;n++) await new Promise(resolve=>setImmediate(resolve));
};
const wait = (source, state, sessionId='wait-test') => events.emit('ghostty-peon:wait', {
 source, state, sessionId, cwd:ctx.cwd,
});
await emit('session_start', {reason:'reload'});
const end = () => emit('agent_end', {messages:[]});
"""


class PiWaitStatusTests(unittest.TestCase):
    def run_scenario(self, script):
        with hook_test_env() as (_root, env, _dirs):
            result = subprocess.run(
                ['node', '--experimental-strip-types', '--input-type=module', '-e',
                 BOOTSTRAP + textwrap.dedent(script)],
                cwd=REPO_ROOT, env=env, text=True, capture_output=True, timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_both_waits_remain_working_until_resumed_turn_finishes(self):
        self.run_scenario("""
            for (const source of ['subagent_wait', 'schedule_wakeup']) {
                seed();
                wait(source, 'waiting');
                await end();
                assert.equal(title(), '🌀 fix-waits', source + ' must not look finished');
                idle = false;
                wait(source, 'resuming');
                await emit('agent_start');
                assert.equal(title(), '🌀 fix-waits');
                idle = true;
                await end();
                assert.equal(title(), '🌿 fix-waits');
            }
        """)

    def test_cancel_and_overlapping_waits(self):
        self.run_scenario("""
            wait('schedule_wakeup', 'waiting');
            wait('subagent_wait', 'waiting');
            await end();
            wait('schedule_wakeup', 'idle');
            await emit('agent_settled');
            assert.equal(title(), '🌀 fix-waits');
            wait('subagent_wait', 'resuming');
            await emit('agent_start');
            await end();
            assert.equal(title(), '🌿 fix-waits');
            wait('schedule_wakeup', 'waiting');
            await end();
            wait('schedule_wakeup', 'idle');
            await emit('agent_settled');
            assert.equal(title(), '🌿 fix-waits', 'cancel while idle must clear working');
        """)

    def test_restore_query_and_attention_priority(self):
        self.run_scenario("""
            events.on('ghostty-peon:wait-query', ({sessionId}) => {
                wait('schedule_wakeup', 'waiting', sessionId);
            });
            seed('🌿');
            await emit('session_start', {reason:'reload'});
            assert.equal(title(), '🌀 fix-waits');
            for (const emoji of ['⭐', '🔥']) {
                seed(emoji);
                wait('schedule_wakeup', 'waiting');
                await end();
                assert.equal(title(), emoji + ' fix-waits');
            }
        """)

    def test_late_stop_cannot_overwrite_new_wait(self):
        self.run_scenario("""
            let release;
            globalThis.stopHookGate = new Promise(resolve => release = resolve);
            const stopping = end();
            while (!globalThis.stopHookStarted) await new Promise(resolve => setImmediate(resolve));
            wait('subagent_wait', 'waiting');
            release();
            await stopping;
            assert.equal(title(), '🌀 fix-waits');
        """)

    def test_tree_navigation_and_shutdown_discard_old_waits(self):
        self.run_scenario("""
            let state = 'waiting';
            events.on('ghostty-peon:wait-query', () => wait('schedule_wakeup', state));
            await emit('session_tree');
            assert.equal(title(), '🌀 fix-waits');
            state = 'idle';
            await emit('session_tree');
            assert.equal(title(), '🌿 fix-waits');
            await emit('session_shutdown', {reason:'reload'});
            assert.equal(events.listenerCount('ghostty-peon:wait'), 0);
            wait('schedule_wakeup', 'waiting');
            await emit('agent_settled');
            assert.equal(title(), '🌿 fix-waits');

            // An owner can restore and consume an overdue wait before Ghostty starts.
            extension(pi);
            seed();
            wait('schedule_wakeup', 'waiting');
            wait('schedule_wakeup', 'idle');
            await emit('session_start', {reason:'reload'});
            assert.equal(title(), '🌿 fix-waits');
        """)

    def test_failed_immediate_and_unrelated_activity_do_not_hold_working(self):
        self.run_scenario("""
            for (const source of ['subagent_wait', 'schedule_wakeup']) {
                seed();
                await emit('tool_result', {toolName:source, isError:true});
                await end();
                assert.equal(title(), '🌿 fix-waits');
            }
            seed();
            await emit('tool_result', {toolName:'subagent_wait', details:{wait:{status:'immediate'}}});
            wait('subagent_wait', 'waiting', 'other-session');
            wait('unknown-source', 'waiting');
            await end();
            assert.equal(title(), '🌿 fix-waits');
        """)


if __name__ == '__main__':
    unittest.main()
