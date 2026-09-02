import assert from 'node:assert/strict'
import test from 'node:test'

import { emptyDraft, emptyMember, visibleProfiles } from '../src/components/services/serviceModels.ts'

test('single workspace only displays the first profile without deleting saved profiles', () => {
  const draft = emptyDraft(8234)
  draft.members.push(emptyMember(1), emptyMember(2))

  assert.deepEqual(visibleProfiles(draft), [draft.members[0]])
  assert.equal(draft.members.length, 3)
})

test('multi workspace displays every configured profile', () => {
  const draft = emptyDraft(8234)
  draft.members.push(emptyMember(1), emptyMember(2))
  draft.mode = 'multi'

  assert.deepEqual(visibleProfiles(draft), draft.members)
})
