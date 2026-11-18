// Shared bounded radio transport, protocol v2. Keep both copies identical.
const GROUP = 47
radio.setGroup(GROUP)
radio.setFrequencyBand(7)
radio.setTransmitPower(6)
const HEX = "0123456789abcdef"
const RADIO_ID_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
const FRAGMENTS = "0123456789abc"
const FRAGMENT_BYTES = 8
let nextId = randint(0, 65535)
const radioBootPrefix = hex4(randint(0, 65535)) + hex4(randint(0, 65535))

function hex4(n: number): string {
    return HEX.charAt((n >> 12) & 15) + HEX.charAt((n >> 8) & 15) + HEX.charAt((n >> 4) & 15) + HEX.charAt(n & 15)
}
function newId(): string { nextId = (nextId + 1) & 65535; return hex4(nextId) }
function isHex(s: string): boolean {
    for (let i = 0; i < s.length; i++) if (HEX.indexOf(s.charAt(i)) < 0) return false
    return s.length > 0
}
// Encode exactly 48 bits as eight ASCII characters to leave room for fragments.
function radioId(hex: string): string {
    let result = ""
    for (let i = 0; i < 12; i += 3) {
        const bits = (HEX.indexOf(hex.charAt(i)) << 8)
            | (HEX.indexOf(hex.charAt(i + 1)) << 4) | HEX.indexOf(hex.charAt(i + 2))
        result += RADIO_ID_ALPHABET.charAt(bits >> 6) + RADIO_ID_ALPHABET.charAt(bits & 63)
    }
    return result
}
function isRadioId(id: string): boolean {
    if (id.length != 8) return false
    for (let i = 0; i < id.length; i++) if (RADIO_ID_ALPHABET.indexOf(id.charAt(i)) < 0) return false
    return true
}
function radioTraceId(id: string): string {
    // USB telemetry keeps its four-hex diagnostic field. No ACK uses this hint.
    return hex4((RADIO_ID_ALPHABET.indexOf(id.charAt(5)) << 12)
        | (RADIO_ID_ALPHABET.indexOf(id.charAt(6)) << 6) | RADIO_ID_ALPHABET.indexOf(id.charAt(7)))
}
function safeText(s: string): boolean {
    if (s.length < 1 || s.length > 80) return false
    for (let i = 0; i < s.length; i++) if (s.charCodeAt(i) < 32 || s.charCodeAt(i) > 126 || s.charAt(i) == "|") return false
    return true
}
// Match the serial protocol's wrapping ground uptime clock.
function clockMs(): number { return input.runningTime() & 0x3fffffff }
function millisUntil(deadline: number): number {
    return ((deadline - clockMs() + 0x20000000) & 0x3fffffff) - 0x20000000
}

class Transmission {
    id: string
    body: string
    tag: string
    deadline: number
    tries = 0
    sentAt = 0

    constructor(body: string, tag: string, deadline: number, id: string) {
        this.id = id || radioId(radioBootPrefix + newId())
        this.body = body
        this.tag = tag
        this.deadline = deadline
    }

    expired(): boolean {
        return this.deadline >= 0 && millisUntil(this.deadline) <= 0
    }
}

let outgoing: Transmission[] = []
let active: Transmission = null
let emergency: Transmission = null

function enqueue(body: string, tag: string, deadline = -1, id = ""): boolean {
    if (outgoing.length >= 8 || !body.length || body.length > FRAGMENT_BYTES * 12) return false
    outgoing.push(new Transmission(body, tag, deadline, id))
    return true
}

function enqueueEmergency(): void {
    // A second press while a MAYDAY is outstanding refers to the same alert.
    if (!emergency) emergency = new Transmission("E|MAYDAY", "MAYDAY", -1, "")
    displayPriority = "MAYDAY PENDING"
}

function stopQueued(tag: string): void {
    if (active && active.tag == tag) active = null
    for (let i = outgoing.length - 1; i >= 0; i--) {
        if (outgoing[i].tag == tag) outgoing.removeAt(i)
    }
}

function complete(tx: Transmission, result: string): void {
    if (tx == emergency) emergency = null
    if (tx == active) active = null
    delivered(tx.tag, result)
}
let rxIds: string[] = []
let rxCounts: number[] = []
let rxMasks: number[] = []
let rxParts: string[][] = []
let rxTimes: number[] = []
let doneIds: string[] = []
let doneTimes: number[] = []
let lastSeen = -10000
let lastRssi = -128
function prune(): void {
    for (let i = rxIds.length - 1; i >= 0; i--) if (input.runningTime() - rxTimes[i] > 3000) {
        rxIds.removeAt(i); rxCounts.removeAt(i); rxMasks.removeAt(i); rxParts.removeAt(i); rxTimes.removeAt(i)
    }
    while (doneTimes.length && input.runningTime() - doneTimes[0] > 30000) { doneIds.shift(); doneTimes.shift() }
}
function receiveComplete(body: string, id: string, rssi: number): void {
    if (!acceptBody(body)) return
    if (doneIds.length >= 32) { doneIds.shift(); doneTimes.shift() }
    doneIds.push(id); doneTimes.push(input.runningTime())
    radio.sendString("K" + id)
    lastSeen = input.runningTime(); lastRssi = rssi
    received(body, id, rssi)
}
radio.onReceivedString(function (packet: string) {
    if (packet.length > 19 || packet.length < 5) return
    const kind = packet.charAt(0)
    const rssi = radio.receivedPacket(RadioPacketProperty.SignalStrength)
    if (kind == "P" || kind == "Q") {
        // Older radio firmware must not look connected through probe-only traffic.
        if (packet.charAt(1) != "2") return
        const probe = packet.substr(2)
        if (probe.length != 4 || !isHex(probe)) return
        if (kind == "P") onProbe(probe, rssi)
        else onProbeReply(probe, rssi)
        return
    }
    const id = packet.substr(1, 8)
    if (!isRadioId(id)) return
    if (kind == "K" && packet.length == 9) {
        const tx = emergency && id == emergency.id ? emergency : active
        if (tx && id == tx.id) {
            lastSeen = input.runningTime(); lastRssi = rssi
            // The ACK is evidence that the aircraft accepted an earlier attempt.
            complete(tx, "RECEIVED")
        }
        return
    }
    if (kind != "D" || packet.length < 12) return
    const index = FRAGMENTS.indexOf(packet.charAt(9))
    const count = FRAGMENTS.indexOf(packet.charAt(10))
    if (index < 0 || count < 1 || index >= count || (index < count - 1 && packet.length != 19)) return
    prune()
    if (doneIds.indexOf(id) >= 0) { radio.sendString("K" + id); return }
    if (count == 1) {
        // A complete MAYDAY (one fragment) must bypass the partial-message pool.
        receiveComplete(packet.substr(11), id, rssi)
        return
    }
    let slot = rxIds.indexOf(id)
    if (slot < 0) {
        if (rxIds.length >= 4) return
        slot = rxIds.length
        rxIds.push(id); rxCounts.push(count); rxMasks.push(0); rxTimes.push(input.runningTime())
        const parts: string[] = []
        for (let i = 0; i < count; i++) parts.push("")
        rxParts.push(parts)
    }
    if (rxCounts[slot] != count) return
    const part = packet.substr(11)
    if ((rxMasks[slot] & (1 << index)) && rxParts[slot][index] != part) return
    rxParts[slot][index] = part
    rxMasks[slot] = rxMasks[slot] | (1 << index)
    if (rxMasks[slot] == (1 << count) - 1) {
        let body = ""
        for (let i = 0; i < count; i++) body += rxParts[slot][i]
        rxTimes[slot] = -10000
        receiveComplete(body, id, rssi)
    }
})
basic.forever(function () {
    prune()
    let expired: string[] = null
    for (let i = outgoing.length - 1; i >= 0; i--) {
        const queued = outgoing[i]
        if (queued.expired()) {
            outgoing.removeAt(i)
            if (!expired) expired = []
            expired.push(queued.tag)
        }
    }
    // Serial writes can yield to the cancellation reader. Finish changing the
    // queue before reporting outcomes.
    if (expired) {
        for (let i = 0; i < expired.length; i++) delivered(expired[i], "EXPIRED")
    }
    if (active && active.expired()) complete(active, "EXPIRED")
    if (!active && outgoing.length && !emergency) active = outgoing.shift()
    const tx = emergency || active
    if (tx && (tx.tries == 0 || input.runningTime() - tx.sentAt >= 650)) {
        if (tx.tries >= 3) {
            complete(tx, "RADIO_TIMEOUT")
        } else {
            const count = Math.ceil(tx.body.length / FRAGMENT_BYTES)
            tx.tries += 1
            for (let i = 0; i < count; i++) {
                // Yielding between fragments allows ACK, cancellation and MAYDAY to
                // take effect before emitting another fragment.
                if (tx != (emergency || active) || tx.expired()) break
                radio.sendString("D" + tx.id + FRAGMENTS.charAt(i) + FRAGMENTS.charAt(count)
                    + tx.body.substr(i * FRAGMENT_BYTES, FRAGMENT_BYTES))
                basic.pause(12)
            }
            tx.sentAt = input.runningTime()
        }
    }
    basic.pause(20)
})
let displayQueue: string[] = []
let displayPriority = ""
function displayText(s: string): void {
    if (displayQueue.length < 8) displayQueue.push(s)
}
// Scrolling yields in its own fiber; packet receive handlers never scroll.
basic.forever(function () {
    if (displayPriority) {
        const text = displayPriority
        displayPriority = ""
        basic.showString(text, 90)
    } else if (displayQueue.length) {
        basic.showString(displayQueue.shift(), 90)
    }
    basic.pause(50)
})
