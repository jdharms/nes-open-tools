; HalfSipHash-2-4 with 32-bit output, over the payload's 35-byte body.
;
; The message is always 8 whole 32-bit words and a 3-byte tail. The spec's
; final block is the tail bytes with the message length in the top byte, so
; with the length stored just past the body, at QrPayload + 35, the final block
; is simply a ninth word read in place: there is no separate tail path. The MAC
; then overwrites that byte. outlen is always 4, so the $EE/$DD tweaks and the
; second set of finalization rounds do not exist here either.
;
; State is four little-endian 32-bit words at QrHashState. The helpers take a
; destination word offset in X and a source word offset in Y; every one of them
; is free to clobber A, X and Y, so nothing may be held in a register across a
; call.

V0 = 0
V1 = 4
V2 = 8
V3 = 12

QrHashCount  = QrHashTemp + 0       ; byte counter inside add/xor
QrHashOffset = QrHashTemp + 1       ; message offset, 0..32 step 4
QrHashRounds = QrHashTemp + 2       ; finalization round counter

; --------------------------------------------------------------------------
; 32-bit primitives
; --------------------------------------------------------------------------

; v[X] += v[Y]. DEC leaves carry alone, which is what carries the add along.
QrHashAdd:
        clc
        lda #4
        sta QrHashCount
@loop:
        lda QrHashState,x
        adc QrHashState,y
        sta QrHashState,x
        inx
        iny
        dec QrHashCount
        bne @loop
        rts

; v[X] ^= v[Y]
QrHashXor:
        lda #4
        sta QrHashCount
@loop:
        lda QrHashState,x
        eor QrHashState,y
        sta QrHashState,x
        inx
        iny
        dec QrHashCount
        bne @loop
        rts

; v[X] = rotl(v[X], 8). Little-endian, so every byte moves up one and the top
; byte wraps into the bottom.
QrHashRotl8:
        lda QrHashState + 3,x
        pha
        lda QrHashState + 2,x
        sta QrHashState + 3,x
        lda QrHashState + 1,x
        sta QrHashState + 2,x
        lda QrHashState + 0,x
        sta QrHashState + 1,x
        pla
        sta QrHashState + 0,x
        rts

; v[X] = rotl(v[X], 16)
QrHashRotl16:
        jsr QrHashRotl8
        jmp QrHashRotl8

; v[X] = rotr(v[X], 1). The carry out of bit 0 goes back into bit 31.
QrHashRotr1:
        lda QrHashState + 0,x
        lsr a
        ror QrHashState + 3,x
        ror QrHashState + 2,x
        ror QrHashState + 1,x
        ror QrHashState + 0,x
        rts

; The four rotations the round schedule actually asks for. Each is expressed as
; the nearest whole-byte rotation plus at most three single-bit ones, which is
; cheaper than rotating five, seven or thirteen times.
QrHashRotl5:
        jsr QrHashRotl8
        ; falls through: rotl 8 then rotr 3 is rotl 5
QrHashRotr3:
        jsr QrHashRotr1
        jsr QrHashRotr1
        jmp QrHashRotr1

QrHashRotl7:
        jsr QrHashRotl8
        jmp QrHashRotr1

QrHashRotl13:
        jsr QrHashRotl16
        jmp QrHashRotr3

; --------------------------------------------------------------------------
; One SipRound
; --------------------------------------------------------------------------

QrHashSipRound:
        ldx #V0
        ldy #V1
        jsr QrHashAdd                   ; v0 += v1
        ldx #V1
        jsr QrHashRotl5                 ; v1 = rotl(v1, 5)
        ldx #V1
        ldy #V0
        jsr QrHashXor                   ; v1 ^= v0
        ldx #V0
        jsr QrHashRotl16                ; v0 = rotl(v0, 16)
        ldx #V2
        ldy #V3
        jsr QrHashAdd                   ; v2 += v3
        ldx #V3
        jsr QrHashRotl8                 ; v3 = rotl(v3, 8)
        ldx #V3
        ldy #V2
        jsr QrHashXor                   ; v3 ^= v2
        ldx #V0
        ldy #V3
        jsr QrHashAdd                   ; v0 += v3
        ldx #V3
        jsr QrHashRotl7                 ; v3 = rotl(v3, 7)
        ldx #V3
        ldy #V0
        jsr QrHashXor                   ; v3 ^= v0
        ldx #V2
        ldy #V1
        jsr QrHashAdd                   ; v2 += v1
        ldx #V1
        jsr QrHashRotl13                ; v1 = rotl(v1, 13)
        ldx #V1
        ldy #V2
        jsr QrHashXor                   ; v1 ^= v2
        ldx #V2
        jmp QrHashRotl16                ; v2 = rotl(v2, 16)

; --------------------------------------------------------------------------
; The MAC
;
; In:  35 bytes of body at QrPayload, 8-byte key at QrHashKey.
; Out: 4 bytes of MAC at QrPayload + 35.
; --------------------------------------------------------------------------

QrHashMac:
        lda #QrBodyLen                  ; the final block's top byte
        sta QrPayload + QrBodyLen
        ; v0 = k0, v1 = k1
        ldx #0
@key:
        lda QrHashKey,x
        sta QrHashState,x
        inx
        cpx #8
        bne @key
        ; v2 = "gyle" ^ k0, v3 = "bdet" ^ k1
        ldx #0
@seed:
        lda QrHashSeed,x
        eor QrHashKey,x
        sta QrHashState + V2,x
        inx
        cpx #8
        bne @seed

        lda #0
        sta QrHashOffset
@block:
        ldy QrHashOffset                ; v3 ^= m
        ldx #0
@xor3:
        lda QrPayload,y
        eor QrHashState + V3,x
        sta QrHashState + V3,x
        iny
        inx
        cpx #4
        bne @xor3

        jsr QrHashSipRound
        jsr QrHashSipRound

        ldy QrHashOffset                ; v0 ^= m
        ldx #0
@xor0:
        lda QrPayload,y
        eor QrHashState + V0,x
        sta QrHashState + V0,x
        iny
        inx
        cpx #4
        bne @xor0

        lda QrHashOffset
        clc
        adc #4
        sta QrHashOffset
        cmp #QrBodyLen + 1              ; eight words, then the final block
        bne @block

        lda QrHashState + V2            ; v2 ^= $FF (outlen 4)
        eor #$FF
        sta QrHashState + V2

        lda #4
        sta QrHashRounds
@final:
        jsr QrHashSipRound
        dec QrHashRounds
        bne @final

        ldx #0                          ; mac = v1 ^ v3
@out:
        lda QrHashState + V1,x
        eor QrHashState + V3,x
        sta QrPayload + QrBodyLen,x
        inx
        cpx #4
        bne @out
        rts

QrHashSeed:
        .byte $65, $67, $79, $6C        ; $6C796765
        .byte $62, $64, $65, $74        ; $74656462
