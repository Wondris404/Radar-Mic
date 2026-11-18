// Shared reliable bounded radio transport, protocol v1. Keep both copies identical.
const GROUP = 47
radio.setGroup(GROUP)
radio.setFrequencyBand(7)
radio.setTransmitPower(6)
let nextId = randint(0, 65535)
function hex4(n: number): string {
    const digits = "0123456789abcdef"
    return digits.charAt((n >> 12) & 15) + digits.charAt((n >> 8) & 15) + digits.charAt((n >> 4) & 15) + digits.charAt(n & 15)
}
function newId(): string { nextId = (nextId + 1) & 65535; return hex4(nextId) }
function isHex(s: string): boolean {
    for (let i = 0; i < s.length; i++) if ("0123456789abcdef".indexOf(s.charAt(i)) < 0) return false
    return s.length > 0
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

    constructor(body: string, tag: string, deadline: number) {
        this.id = newId()
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

function enqueue(body: string, tag: string, deadline = -1): boolean {
    if (outgoing.length >= 8 || !body.length || body.length > 96) return false
    outgoing.push(new Transmission(body, tag, deadline))
    return true
}

function enqueueEmergency(): void {
    // A second press while a MAYDAY is outstanding refers to the same alert.
    if (!emergency) emergency = new Transmission("E|MAYDAY", "MAYDAY", -1)
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
radio.onReceivedString(function (packet: string) {
    if (packet.length > 19 || packet.length < 5 || !isHex(packet.substr(1, 4))) return
    const id = packet.substr(1, 4)
    const rssi = radio.receivedPacket(RadioPacketProperty.SignalStrength)
    if (packet.charAt(0) == "K" && packet.length == 5) {
        const tx = emergency && id == emergency.id ? emergency : active
        if (tx && id == tx.id) {
            lastSeen = input.runningTime(); lastRssi = rssi
            // The ACK is evidence that the aircraft accepted an earlier attempt.
            complete(tx, "RECEIVED")
        }
        return
    }
    if (packet.charAt(0) == "P" && packet.length == 5) { onProbe(id, rssi); return }
    if (packet.charAt(0) == "Q" && packet.length == 5) { onProbeReply(id, rssi); return }
    if (packet.charAt(0) != "D" || packet.length < 8) return
    const index = "01234567".indexOf(packet.charAt(5))
    const count = "12345678".indexOf(packet.charAt(6)) + 1
    if (index < 0 || count < 1 || index >= count || (index < count - 1 && packet.length != 19)) return
    prune()
    if (doneIds.indexOf(id) >= 0) { radio.sendString("K" + id); return }
    let slot = rxIds.indexOf(id)
    if (slot < 0) {
        if (rxIds.length >= 4) return
        slot = rxIds.length
        rxIds.push(id); rxCounts.push(count); rxMasks.push(0); rxTimes.push(input.runningTime())
        rxParts.push(["", "", "", "", "", "", "", ""])
    }
    if (rxCounts[slot] != count) return
    const part = packet.substr(7)
    if ((rxMasks[slot] & (1 << index)) && rxParts[slot][index] != part) return
    rxParts[slot][index] = part
    rxMasks[slot] = rxMasks[slot] | (1 << index)
    if (rxMasks[slot] == (1 << count) - 1) {
        let body = ""
        for (let i = 0; i < count; i++) body += rxParts[slot][i]
        if (!acceptBody(body)) return
        if (doneIds.length >= 32) { doneIds.shift(); doneTimes.shift() }
        doneIds.push(id); doneTimes.push(input.runningTime())
        rxTimes[slot] = -10000
        radio.sendString("K" + id)
        lastSeen = input.runningTime(); lastRssi = rssi
        received(body, id, rssi)
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
            const count = Math.ceil(tx.body.length / 12)
            tx.tries += 1
            for (let i = 0; i < count; i++) {
                // Yielding between fragments allows ACK, cancellation and MAYDAY to
                // take effect before emitting another fragment.
                if (tx != (emergency || active) || tx.expired()) break
                radio.sendString("D" + tx.id + i + count + tx.body.substr(i * 12, 12))
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
