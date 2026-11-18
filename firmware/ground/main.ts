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
function emit(kind: string, id: string, fields: string): void { serial.writeLine("1|" + kind + "|" + id + "|" + fields) }
function acceptBody(body: string): boolean {
    return body == "H|AIR101" || body == "E|POSITION" || body == "E|LANDING" || body == "E|MAYDAY"
}
function received(body: string, id: string, rssi: number): void {
    emit("LINK", id, "AIR101|UP|" + rssi)
    if (body.substr(0, 2) == "E|") emit("EVENT", id, "AIR101|" + body.substr(2) + "|" + rssi)
}
function delivered(tag: string, ok: boolean): void {
    if (tag == "HEART") return
    const i = commandIds.indexOf(tag)
    if (i >= 0) {
        commandResults[i] = ok ? "DELIVERED" : "RADIO_TIMEOUT"
        emit(ok ? "ACK" : "ERROR", tag, commandResults[i])
    }
}
let probeId = ""
let probeStart = 0
function onProbe(id: string, rssi: number): void {}
function onProbeReply(id: string, rssi: number): void {
    if (id != probeId || !probeId) return
    const elapsed = input.runningTime() - probeStart
    emit("RTT", id, "OK|" + elapsed + "|" + rssi)
    lastSeen = input.runningTime(); lastRssi = rssi
    emit("LINK", id, "AIR101|UP|" + rssi)
    probeId = ""
}
function startProbe(): void {
    if (!probeId) {
        probeId = newId(); probeStart = input.runningTime()
        radio.sendString("P" + probeId)
    }
}
function decimal(s: string, low: number, high: number): boolean {
    if (!s.length || s.length > 3) return false
    for (let i = 0; i < s.length; i++) if ("0123456789".indexOf(s.charAt(i)) < 0) return false
    return parseInt(s) >= low && parseInt(s) <= high
}
function command(line: string): void {
    const p = line.split("|")
    if (p.length != 4 || p[0] != "1" || p[2].length != 4 || !isHex(p[2])) { emit("ERROR", "0000", "BAD_RECORD"); return }
    const kind = p[1], id = p[2], value = p[3]
    const now = input.runningTime()
    while (commandTimes.length && now - commandTimes[0] > 30000) {
        commandIds.shift(); commandBodies.shift(); commandResults.shift(); commandTimes.shift()
    }
    let slot = commandIds.indexOf(id)
    if (slot >= 0) {
        if (commandBodies[slot] != line) { emit("ERROR", id, "ID_CONFLICT"); return }
        const result = commandResults[slot]
        if (result) emit(result == "RADIO_TIMEOUT" ? "ERROR" : "ACK", id, result)
        return
    }
    const valid = (kind == "TEXT" && safeText(value)) || (kind == "SCAN" && (value == "0" || value == "1")) || (kind == "THRESH" && decimal(value, 2, 400)) || (kind == "PING" && value == "AIR101")
    if (!valid) { emit("ERROR", id, "BAD_COMMAND"); return }
    if (commandIds.length >= 32) { emit("ERROR", id, "BUSY"); return }
    if (kind == "TEXT" && !enqueue("T|" + value, id)) { emit("ERROR", id, "BUSY"); return }
    commandIds.push(id); commandBodies.push(line); commandResults.push(""); commandTimes.push(now)
    if (kind == "TEXT") return
    if (kind == "SCAN") scanning = value == "1"
    if (kind == "THRESH") threshold = parseInt(value)
    if (kind == "PING") startProbe()
    slot = commandIds.indexOf(id); commandResults[slot] = "APPLIED"
    emit("ACK", id, "APPLIED")
}
// Poll characters with a bound instead of allowing an unterminated line to allocate forever.
let serialLine = ""
let serialDiscard = false
basic.forever(function () {
    const data = serial.readString()
    for (let i = 0; i < data.length; i++) {
        const c = data.charAt(i)
        if (c == "\n") {
            if (!serialDiscard) command(serialLine)
            serialLine = ""; serialDiscard = false
        } else if (c != "\r" && !serialDiscard) {
            serialLine += c
            if (serialLine.length > 240) { serialLine = ""; serialDiscard = true; emit("ERROR", "0000", "LINE_TOO_LONG") }
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
        sensorStatus = d >= 2 && d <= 400 ? "VALID" : "NO_TARGET"
        if (sensorStatus != "VALID") d = 0
        led.plot(2, 2)
        if (d > 0 && d <= threshold) led.plot(0, 0)
        else led.unplot(0, 0)
    }
    emit("SONAR", "0000", sensorStatus + "|" + d)
    basic.pause(250)
})
basic.forever(function () {
    emit("HELLO", "0000", "GROUND01|47")
    emit("HEART", "0000", "GROUND01|" + input.runningTime())
    if (input.runningTime() - lastSeen >= 7000) emit("LINK", "0000", "AIR101|LOST|" + lastRssi)
    enqueue("H|GROUND01", "HEART")
    basic.pause(2000)
})
let nextProbeAt = 0
basic.forever(function () {
    if (probeId && input.runningTime() - probeStart >= 1000) {
        emit("RTT", probeId, "LOST|0|" + lastRssi); probeId = ""
    }
    if (!probeId && input.runningTime() >= nextProbeAt) { startProbe(); nextProbeAt = input.runningTime() + 2000 }
    basic.pause(50)
})
