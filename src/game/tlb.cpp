// TLB mapping. First version: log the arguments and do nothing.
//
// The game maps per-fighter data blocks at virtual 0x00010000 to 0x000BA000 (see
// PLAN.md, risks table, "TLB mapping"). The runtime has no TLB support, so the game
// calls land here. Until real mapping is written, the first read of a mapped
// address will crash; these logs show what was asked for just before that.
//
// libultra signatures (public, from the N64 SDK headers):
//   void osMapTLB(s32 index, OSPageMask pm, void* vaddr, u32 evenpaddr, u32 oddpaddr, s32 asid);
//   void osUnmapTLB(s32 index);
#include <cstdio>

#include "recomp.h"

extern "C" void osMapTLB_recomp(uint8_t* rdram, recomp_context* ctx) {
    // Arguments 5 and 6 are passed on the stack, at sp + 0x10 and sp + 0x14.
    uint32_t oddpaddr = (uint32_t)MEM_W(0x10, ctx->r29);
    int32_t asid = (int32_t)MEM_W(0x14, ctx->r29);
    fprintf(stderr,
        "[kigold][tlb] osMapTLB index=%d pagemask=0x%08X vaddr=0x%08X evenpaddr=0x%08X oddpaddr=0x%08X asid=%d ra=0x%08X (NOT MAPPED, log only)\n",
        (int32_t)ctx->r4, (uint32_t)ctx->r5, (uint32_t)ctx->r6, (uint32_t)ctx->r7,
        oddpaddr, asid, (uint32_t)ctx->r31);
}

extern "C" void osUnmapTLB_recomp(uint8_t* rdram, recomp_context* ctx) {
    (void)rdram;
    fprintf(stderr, "[kigold][tlb] osUnmapTLB index=%d ra=0x%08X (log only)\n",
        (int32_t)ctx->r4, (uint32_t)ctx->r31);
}
