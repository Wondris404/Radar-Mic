serial.redirectToUSB()
serial.setBaudRate(BaudRate.BaudRate115200)
serial.setRxBufferSize(254)
serial.setTxBufferSize(254)
let scanning = true
let threshold = 50
let sensorStatus = "STARTING"
let commandIds: string[] = []
let commandBodies: string[] = []
let commandResults: string[] = []
let commandTimes: number[] = []
const bootId = hex4(randint(0, 65535)) + hex4(randint(0, 65535)) + hex4(randint(0, 65535)) + hex4(randint(0, 65535))

function emit(kind: string, id: string, fields: string): void {
    // MakeCode writeLine pads to a 32-byte boundary before CRLF.
    serial.writeString("2|" + kind + "|" + id + "|" + fields + "\r\n")
}
function acceptBody(body: string): boolean {
    return body == "H|AIR101" || body == "E|POSITION" || body == "E|LANDING" || body == "E|MAYDAY"
}
function received(body: string, id: string, rssi: number): void {
    const trace = radioTraceId(id)
    emit("LINK", trace, "AIR101|UP|" + rssi)
    if (body.substr(0, 2) == "E|") emit("EVENT", trace, "AIR101|" + body.substr(2) + "|" + rssi)
}
function reply(id: string, result: string): void {
    const acknowledged = result == "RECEIVED" || result == "APPLIED" || result == "CANCELLED"
    emit(acknowledged ? "ACK" : "ERROR", id, result)
}
function delivered(tag: string, result: string): void {
    if (tag == "HEART") return
    const i = commandIds.indexOf(tag)
    if (i >= 0 && !commandResults[i]) {
        commandResults[i] = result
        reply(tag, result)
    }
}
let probeId = ""
let probeStart = 0
const PROBE_TIMEOUT_MS = 1000
const SONAR_MIN_CM = 4
const SONAR_MAX_CM = 400

function onProbe(id: string, rssi: number): void {}
function onProbeReply(id: string, rssi: number): void {
    if (id != probeId || !probeId) return
    const now = input.runningTime()
    const elapsed = now - probeStart
    if (elapsed >= PROBE_TIMEOUT_MS) return
    // Serial writes may yield. Retire the probe before the timeout fiber runs.
    probeId = ""
    lastSeen = now; lastRssi = rssi
    emit("RTT", id, "OK|" + elapsed + "|" + rssi)
    emit("LINK", id, "AIR101|UP|" + rssi)
}
function startProbe(): void {
    if (!probeId) {
        probeId = newId(); probeStart = input.runningTime()
        radio.sendString("P2" + probeId)
    }
}
function decimal(s: string, low: number, high: number): boolean {
    if (!s.length || s.length > 3) return false
    for (let i = 0; i < s.length; i++) if ("0123456789".indexOf(s.charAt(i)) < 0) return false
    return parseInt(s) >= low && parseInt(s) <= high
}
function remember(id: string, line: string, result: string): void {
    commandIds.push(id)
    commandBodies.push(line)
    commandResults.push(result)
    commandTimes.push(input.runningTime())
}

function command(line: string): void {
    const p = line.split("|")
    if (p.length < 4 || p[0] != "2" || p[2].length != 32 || !isHex(p[2])) {
        emit("ERROR", "0000", "BAD_RECORD")
        return
    }
    const kind = p[1], id = p[2], value = p[3]
    const now = input.runningTime()
    while (commandTimes.length && now - commandTimes[0] > 30000) {
        commandIds.shift(); commandBodies.shift(); commandResults.shift(); commandTimes.shift()
    }
    const slot = commandIds.indexOf(id)
    if (kind == "CANCEL") {
        if (p.length != 4) { reply(id, "BAD_COMMAND"); return }
        if (value != bootId) { reply(id, "STALE_BOOT"); return }
        if (slot >= 0) {
            if (commandResults[slot]) reply(id, commandResults[slot])
            else {
                stopQueued(id)
                delivered(id, "CANCELLED")
            }
        } else if (commandIds.length < 32) {
            // Retain a tombstone in case a retry arrives after cancellation.
            remember(id, "", "CANCELLED")
            reply(id, "CANCELLED")
        } else reply(id, "BUSY")
        return
    }
    if (slot >= 0) {
        if (commandResults[slot] == "CANCELLED") reply(id, "CANCELLED")
        else if (commandBodies[slot] != line) reply(id, "ID_CONFLICT")
        else if (commandResults[slot]) reply(id, commandResults[slot])
        return
    }
    if (kind == "TEXT") {
        if (p.length != 6 || !safeText(p[5]) || !isClock(p[4])) { reply(id, "BAD_COMMAND"); return }
        if (value != bootId) { reply(id, "STALE_BOOT"); return }
        const deadline = parseInt(p[4])
        const remaining = millisUntil(deadline)
        if (remaining <= 0) { reply(id, "EXPIRED"); return }
        if (remaining > 10000) { reply(id, "BAD_COMMAND"); return }
        if (commandIds.length >= 32 || !enqueue("T|" + p[5], id, deadline, radioId(id.substr(0, 12)))) { reply(id, "BUSY"); return }
        remember(id, line, "")
        return
    }
    const valid = (kind == "SCAN" && (value == "0" || value == "1"))
        || (kind == "THRESH" && decimal(value, 2, 400)) || (kind == "PING" && value == "AIR101")
    if (p.length != 4 || !valid) { reply(id, "BAD_COMMAND"); return }
    if (commandIds.length >= 32) { reply(id, "BUSY"); return }
    if (kind == "SCAN") scanning = value == "1"
    if (kind == "THRESH") threshold = parseInt(value)
    if (kind == "PING") startProbe()
    remember(id, line, "APPLIED")
    reply(id, "APPLIED")
}

function isClock(s: string): boolean {
    if (!s.length || s.length > 10) return false
    for (let i = 0; i < s.length; i++) if ("0123456789".indexOf(s.charAt(i)) < 0) return false
    return parseInt(s) <= 0x3fffffff
}
// Poll characters with a bound instead of allowing an unterminated line to allocate forever.
let serialLine = ""
let serialDiscard = false
basic.forever(function () {
    const data = serial.readString()
    for (let i = 0; i < data.length; i++) {
        const c = data.charAt(i)
        if (c == "\n") {
            if (!serialDiscard) {
                if (serialLine.charAt(serialLine.length - 1) == "\r") serialLine = serialLine.substr(0, serialLine.length - 1)
                if (serialLine.length <= 240) command(serialLine)
                else emit("ERROR", "0000", "LINE_TOO_LONG")
            }
            serialLine = ""; serialDiscard = false
        } else if (!serialDiscard) {
            serialLine += c
            if (serialLine.length > 241) { serialLine = ""; serialDiscard = true; emit("ERROR", "0000", "LINE_TOO_LONG") }
        }
    }
    basic.pause(10)
})
input.onButtonPressed(Button.A, function () { scanning = !scanning; displayText(scanning ? "ON" : "OFF") })
input.onButtonPressed(Button.B, function () { displayText(input.runningTime() - lastSeen < 7000 ? "AIR OK " + sensorStatus : "AIR LOST " + sensorStatus) })
basic.forever(function () {
    let d = 0
    sensorStatus = "OFF"
    if (scanning) {
        d = sonarbit.sonarbit_distance(Distance_Unit.Distance_Unit_cm, DigitalPin.P2)
        sensorStatus = d >= SONAR_MIN_CM && d <= SONAR_MAX_CM ? "VALID" : "NO_TARGET"
        if (sensorStatus != "VALID") d = 0
        led.plot(2, 2)
    } else {
        led.unplot(2, 2)
    }
    if (d > 0 && d <= threshold) led.plot(0, 0)
    else led.unplot(0, 0)
    emit("SONAR", "0000", sensorStatus + "|" + d)
    basic.pause(250)
})
basic.forever(function () {
    emit("HELLO", "0000", "GROUND01|47")
    emit("HEART", "0000", "GROUND01|" + bootId + "|" + clockMs())
    if (input.runningTime() - lastSeen >= 7000) emit("LINK", "0000", "AIR101|LOST|" + lastRssi)
    enqueue("H|GROUND01", "HEART")
    basic.pause(2000)
})
let nextProbeAt = 0
basic.forever(function () {
    if (probeId && input.runningTime() - probeStart >= PROBE_TIMEOUT_MS) {
        const id = probeId
        probeId = ""
        emit("RTT", id, "LOST|0|-128")
    }
    if (!probeId && input.runningTime() >= nextProbeAt) { startProbe(); nextProbeAt = input.runningTime() + 2000 }
    basic.pause(50)
})
