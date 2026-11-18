function acceptBody(body: string): boolean {
    return body == "H|GROUND01" || (body.substr(0, 2) == "T|" && safeText(body.substr(2)) && displayQueue.length < 8)
}
function received(body: string, id: string, rssi: number): void {
    if (body.substr(0, 2) == "T|") displayText(body.substr(2))
}
function delivered(tag: string, ok: boolean): void {
    if (tag != "HEART") displayText(ok ? "ACK " + tag : "FAIL " + tag)
}
function onProbe(id: string, rssi: number): void {
    lastSeen = input.runningTime(); lastRssi = rssi
    radio.sendString("Q" + id)
}
function onProbeReply(id: string, rssi: number): void {}
input.onButtonPressed(Button.A, function () { if (!enqueue("E|POSITION", "POSITION")) displayText("BUSY") })
input.onButtonPressed(Button.B, function () { if (!enqueue("E|LANDING", "LANDING")) displayText("BUSY") })
input.onButtonPressed(Button.AB, function () { if (!enqueue("E|MAYDAY", "MAYDAY")) displayText("BUSY") })
basic.forever(function () {
    enqueue("H|AIR101", "HEART")
    basic.pause(2000)
})
displayText("AIR101")
