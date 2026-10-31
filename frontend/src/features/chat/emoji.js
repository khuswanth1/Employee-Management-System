import { local, userKey } from '../../lib/storage'

// A compact emoji set for the composer, grouped for the picker tabs. Plain Unicode: no images or third-party packages.
// Each emoji has searchable words, so "heart", "party" or "coffee" find it.
const E = (s) => s.split('|').map((x) => { const [e, ...w] = x.trim().split(' '); return { e, w: w.join(' ') } })

export const EMOJI_GROUPS = [
  { id: 'smileys', label: 'Smileys', icon: '😀', items: E('😀 grin happy|😃 smile happy|😄 smile laugh|😁 grin beam|😆 laugh squint|😅 sweat relief|😂 joy laugh tears lol|🤣 rofl laugh floor|🙂 slight smile|😉 wink|😊 blush happy|😇 angel innocent|🥰 love hearts adore|😍 heart eyes love|🤩 star struck wow|😘 kiss|😋 yum tasty|😛 tongue|😜 wink tongue silly|🤪 zany crazy|🤗 hug|🤔 thinking hmm|🤨 skeptical eyebrow|😐 neutral|😶 silent|🙄 eye roll|😏 smirk|😌 relieved calm|😴 sleep tired|😪 sleepy|😷 mask sick|🤒 fever sick|🤯 mind blown|😎 cool sunglasses|🥳 party celebrate|😕 confused|😟 worried|😮 surprised wow|😲 astonished|😳 flushed embarrassed|🥺 pleading please|😢 cry sad|😭 sob crying|😤 frustrated|😡 angry mad|😱 scream shocked|🥱 yawn bored') },
  { id: 'gestures', label: 'Gestures', icon: '👍', items: E('👍 thumbs up like yes good|👎 thumbs down dislike no|👌 ok perfect|✌️ peace victory|🤞 fingers crossed luck|🤝 handshake deal|👏 clap applause|🙌 raised hands hooray|🙏 pray thanks please|💪 strong muscle|👋 wave hello bye|🤚 hand stop|✋ high five stop|🖐️ hand|👈 left point|👉 right point|👆 up point|👇 down point|☝️ one up|✍️ writing|🫡 salute|🤙 call me|🫶 heart hands|🙋 raise hand question') },
  { id: 'hearts', label: 'Hearts', icon: '❤️', items: E('❤️ red heart love|🧡 orange heart|💛 yellow heart|💚 green heart|💙 blue heart|💜 purple heart|🖤 black heart|🤍 white heart|💔 broken heart|❣️ heart exclamation|💕 two hearts|💖 sparkling heart|💗 growing heart|💯 hundred perfect|✨ sparkles great|🔥 fire hot lit|⭐ star|🌟 glowing star|🎉 party popper celebrate congratulations|🎊 confetti|🎈 balloon|🎁 gift present|🏆 trophy win|🥇 gold medal first') },
  { id: 'work', label: 'Work', icon: '💼', items: E('💼 briefcase work|📅 calendar date|📆 calendar|📝 memo note|📌 pin|📎 paperclip attach|📊 chart bar report|📈 chart up growth|📉 chart down|💻 laptop computer|🖥️ desktop|📱 phone mobile|☎️ telephone call|📧 email mail|🔔 bell notification|⏰ alarm clock time|⏳ hourglass waiting|✅ check done complete|❌ cross no wrong|⚠️ warning|❓ question|❗ exclamation important|💡 idea bulb|🔒 lock secure|🔑 key|🛠️ tools fix|🐛 bug|🚀 rocket launch|🎯 target goal|🧠 brain think') },
  { id: 'food', label: 'Food', icon: '☕', items: E('☕ coffee tea break|🍵 green tea|🥤 drink|🍺 beer|🍕 pizza|🍔 burger|🍟 fries|🌮 taco|🍜 noodles ramen|🍣 sushi|🍰 cake|🎂 birthday cake|🍪 cookie|🍫 chocolate|🍎 apple|🍌 banana|🍇 grapes|🍓 strawberry|🥗 salad|🍳 egg breakfast|🥐 croissant|🍩 donut') },
  { id: 'nature', label: 'Nature', icon: '🌳', items: E('🌞 sun sunny|🌙 moon night|☁️ cloud|🌧️ rain|⚡ lightning|❄️ snow cold|🌈 rainbow|🌳 tree|🌸 blossom flower|🌻 sunflower|🍀 clover luck|🐶 dog|🐱 cat|🐼 panda|🦊 fox|🐢 turtle|🦋 butterfly|🐝 bee|🐞 ladybug') },
]

const ALL = EMOJI_GROUPS.flatMap((g) => g.items.map((i) => ({ ...i, group: g.label })))

export function searchEmoji(q) {
  const term = q.trim().toLowerCase()
  if (!term) return []
  return ALL.filter((i) => i.w.includes(term) || i.group.toLowerCase().includes(term) || i.e === term).map((i) => i.e).filter((e, n, a) => a.indexOf(e) === n)
}

// ---- recently and frequently used, per person, kept in the browser ---------------------------------------------
const key = (userId, name) => userKey('chat', userId, name)
export function recordEmoji(userId, e) {
  const recent = [e, ...local.get(key(userId, 'emoji.recent'), []).filter((x) => x !== e)].slice(0, 16)
  const freq = { ...local.get(key(userId, 'emoji.freq'), {}) }
  freq[e] = (freq[e] || 0) + 1
  local.set(key(userId, 'emoji.recent'), recent)
  local.set(key(userId, 'emoji.freq'), freq)
}
export const recentEmoji = (userId) => local.get(key(userId, 'emoji.recent'), [])
export const frequentEmoji = (userId, n = 8) => Object.entries(local.get(key(userId, 'emoji.freq'), {})).sort((a, b) => b[1] - a[1]).slice(0, n).map(([e]) => e)

// ---- stickers: recently used and favourites ----------------------------------------------------------------------
export function recordSticker(userId, id) {
  local.set(key(userId, 'sticker.recent'), [id, ...local.get(key(userId, 'sticker.recent'), []).filter((x) => x !== id)].slice(0, 12))
}
export const recentStickers = (userId) => local.get(key(userId, 'sticker.recent'), [])
export const favouriteStickers = (userId) => local.get(key(userId, 'sticker.fav'), [])
export function toggleFavouriteSticker(userId, id) {
  const cur = favouriteStickers(userId)
  const next = cur.includes(id) ? cur.filter((x) => x !== id) : [id, ...cur]
  local.set(key(userId, 'sticker.fav'), next)
  return next
}

export const insertAtCursor = (el, value, insert) => {
  if (!el || typeof el.selectionStart !== 'number') return { value: value + insert, cursor: (value + insert).length }
  const start = el.selectionStart
  const end = el.selectionEnd
  const next = value.slice(0, start) + insert + value.slice(end)
  return { value: next, cursor: start + insert.length }
}

export const fmtDuration = (s) => `${Math.floor((s || 0) / 60)}:${String(Math.floor((s || 0) % 60)).padStart(2, '0')}`
export const fmtSize = (n) => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : n >= 1024 ? `${Math.round(n / 1024)} KB` : `${n || 0} B`)

// ---- attachments: what the browser may offer; the server checks the real content again ------------------------------
export const MAX_FILE_BYTES = 25 * 1024 * 1024
const GROUPS = {
  photo: ['png', 'jpg', 'jpeg', 'gif', 'webp'],
  audio: ['mp3', 'wav', 'ogg', 'oga', 'opus', 'm4a'],
  document: ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'csv', 'md'],
}
export const kindOfFile = (name) => {
  const ext = (name.split('.').pop() || '').toLowerCase()
  return Object.keys(GROUPS).find((k) => GROUPS[k].includes(ext)) || null
}
/** Returns a message if the browser can already tell this file will be refused. */
export function checkFile(f) {
  if (!kindOfFile(f.name)) return `${f.name}: this file type is not allowed. Use photos, audio, PDF, Office documents or text files.`
  if (f.size === 0) return `${f.name}: the file is empty.`
  if (f.size > MAX_FILE_BYTES) return `${f.name}: larger than ${MAX_FILE_BYTES / 1048576} MB (${fmtSize(f.size)}).`
  return null
}
