// NOLF2 Simplified-Chinese self-drawn text renderer.
//
// Hooks CUIPolyString::Render. Matches each string's English source (GetText, ASCII ->
// locale-independent) against a runtime English->Chinese table (exact for plain strings,
// pattern match + value back-fill for %..!d! format templates), then lays the Chinese
// glyphs out as quads sampled from one atlas (font texture swapped around the draw).
// No carriers, no font paging, no CRES edits. Offsets verified vs CSHELL.DLL (chinese_note.md).
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef uint8_t uint8;

extern "C" IMAGE_DOS_HEADER __ImageBase;

static const uintptr_t kTexInterfaceRva  = 0x20E900;
static const uintptr_t kFontMgrGlobalRva = 0x20E8FC;

static const int VF_CreateFormatted = 0x3C / 4;
static const int VF_CreatePoly      = 0x38 / 4;  // CreatePolyString(font,buf,x,y)
static const int VT_CreateTexName   = 0x08 / 4;
static const int VP_GetText   = 0x30 / 4;
static const int VP_GetPolys  = 0x34 / 4;
static const int VP_GetFont   = 0x38 / 4;
static const int VP_GetLength = 0x58 / 4;
static const int VP_Render    = 0x60 / 4;
static const int VP_GetPosition = 0x40 / 4;  // GetPosition(float*,float*)
static const int VF_GetTexture = 0x10 / 4;
static const int VF_SetTexture = 0x48 / 4;
static const int VF_DrawString = 0x78 / 4;  // CUIFont::DrawString(x,y,text)

typedef void  (__cdecl    *SetMasterDatabaseFn)(void*);
typedef void* (__thiscall *CreateFormattedFn)(void*, void*, char*, float, float, int);
typedef void* (__thiscall *CreatePolyFn)(void*, void*, char*, float, float);
typedef int   (__thiscall *RenderFn)(void*, int, int);
typedef int   (__thiscall *TexCreateFromNameFn)(void*, void**, const char*);
typedef const char* (__thiscall *GetTextFn)(void*);
typedef void* (__thiscall *GetPolysFn)(void*);
typedef unsigned short (__thiscall *GetLenFn)(void*);
typedef void* (__thiscall *GetFontFn)(void*);
typedef void* (__thiscall *FontGetTexFn)(void*);
typedef int   (__thiscall *FontSetTexFn)(void*, void*, void*, unsigned char);
typedef int   (__thiscall *GetPosFn)(void*, float*, float*);
typedef void  (__thiscall *DrawStringFn)(void*, float, float, char*);

struct LT_VERTRGBA { uint8 b, g, r, a; };
struct LT_VERTGT { float x, y, z; LT_VERTRGBA rgba; float u, v; };
struct LT_POLYGT4 { LT_VERTGT verts[4]; };

static HMODULE g_original = NULL;
static SetMasterDatabaseFn g_set_master_database = NULL;
static CreateFormattedFn g_orig_create_formatted = NULL;
static CreatePolyFn g_orig_create_polystr = NULL;
static RenderFn g_orig_render_fmt = NULL;
static RenderFn g_orig_render_plain = NULL;
static bool g_fmt_patched = false;
static bool g_plain_patched = false;
static bool g_fontmgr_patched = false;

static void* g_atlas_tex = NULL;
static bool g_atlas_tried = false;
static DrawStringFn g_orig_drawstring = NULL;
static bool g_ds_patched = false;
static void PatchFontDrawString(void* font);  // fwd decl (defined below)

static const int kMaxGlyphs = 4096;
static uint32_t g_cp[kMaxGlyphs];
static float g_u0[kMaxGlyphs], g_v0[kMaxGlyphs], g_u1[kMaxGlyphs], g_v1[kMaxGlyphs];
static float g_adv[kMaxGlyphs];
static int g_glyph_count = 0;
static bool g_metrics_loaded = false;

static uint8_t* g_dict_buf = NULL;
static bool g_dict_loaded = false;
// main (exact-match) section, sorted by english
static int g_main_count = 0;
static const char** g_den = NULL;
static int* g_den_len = NULL;
static int* g_dm = NULL;
static const uint32_t** g_dcps = NULL;
// format-template section (linear scan)
static int g_fmt_count = 0;
static const char** g_fen = NULL;
static int* g_fen_len = NULL;
static int* g_fm = NULL;
static const uint32_t** g_fcps = NULL;

static uintptr_t Base() { return (uintptr_t)g_original; }
static void* TexIface() { return g_original ? *(void**)(Base() + kTexInterfaceRva) : NULL; }

static bool GetRootPath(char* out, DWORD out_size)
{
    char cwd[MAX_PATH] = {0};
    if (GetCurrentDirectoryA(sizeof(cwd), cwd)) {
        char marker[MAX_PATH] = {0};
        lstrcpynA(marker, cwd, sizeof(marker));
        lstrcatA(marker, "\\launchcmds.txt");
        if (GetFileAttributesA(marker) != INVALID_FILE_ATTRIBUTES) {
            lstrcpynA(out, cwd, out_size);
            return true;
        }
    }
    char module_path[MAX_PATH] = {0};
    DWORD len = GetModuleFileNameA((HMODULE)&__ImageBase, module_path, sizeof(module_path));
    if (!len || len >= sizeof(module_path)) return false;
    char* slash = strrchr(module_path, '\\');
    if (!slash) return false;
    *slash = '\0';
    slash = strrchr(module_path, '\\');
    if (!slash) return false;
    *slash = '\0';
    lstrcpynA(out, module_path, out_size);
    return true;
}

static void DebugLine(const char* msg)
{
    OutputDebugStringA("[NOLF2 CN renderer] ");
    OutputDebugStringA(msg);
    OutputDebugStringA("\n");
    char root[MAX_PATH] = {0};
    if (!GetRootPath(root, sizeof(root))) return;
    char path[MAX_PATH] = {0};
    lstrcpynA(path, root, sizeof(path));
    lstrcatA(path, "\\NOLF2_CN\\runtime.log");
    HANDLE h = CreateFileA(path, FILE_APPEND_DATA, FILE_SHARE_READ, NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) return;
    DWORD written = 0;
    WriteFile(h, "[renderer] ", 11, &written, NULL);
    WriteFile(h, msg, lstrlenA(msg), &written, NULL);
    WriteFile(h, "\r\n", 2, &written, NULL);
    CloseHandle(h);
}

static bool LoadMetrics()
{
    if (g_metrics_loaded) return g_glyph_count > 0;
    g_metrics_loaded = true;
    char root[MAX_PATH] = {0};
    if (!GetRootPath(root, sizeof(root))) return false;
    char path[MAX_PATH] = {0};
    lstrcpynA(path, root, sizeof(path));
    lstrcatA(path, "\\NOLF2_CN\\NOLF2CN_ATLAS.MET");
    HANDLE h = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) { DebugLine("atlas .MET not found"); return false; }
    uint8_t hdr[12] = {0};
    DWORD got = 0;
    ReadFile(h, hdr, sizeof(hdr), &got, NULL);
    if (got < 12 || memcmp(hdr, "CNMA", 4) != 0) { CloseHandle(h); return false; }
    uint32_t count = *(uint32_t*)(hdr + 4);
    for (uint32_t i = 0; i < count && g_glyph_count < kMaxGlyphs; ++i) {
        uint8_t rec[24] = {0};
        if (!ReadFile(h, rec, sizeof(rec), &got, NULL) || got < 24) break;
        int k = g_glyph_count++;
        g_cp[k] = *(uint32_t*)(rec + 0);
        g_u0[k] = *(float*)(rec + 4);
        g_v0[k] = *(float*)(rec + 8);
        g_u1[k] = *(float*)(rec + 12);
        g_v1[k] = *(float*)(rec + 16);
        g_adv[k] = *(float*)(rec + 20);
    }
    CloseHandle(h);
    char m[64]; sprintf_s(m, sizeof(m), "metrics loaded: %d glyphs", g_glyph_count);
    DebugLine(m);
    return g_glyph_count > 0;
}

static int LookupGlyph(uint32_t cp)
{
    int lo = 0, hi = g_glyph_count - 1;
    while (lo <= hi) {
        int mid = (lo + hi) / 2;
        if (g_cp[mid] == cp) return mid;
        if (g_cp[mid] < cp) lo = mid + 1; else hi = mid - 1;
    }
    return -1;
}

static bool LoadDict()
{
    if (g_dict_loaded) return g_main_count > 0;
    g_dict_loaded = true;
    char root[MAX_PATH] = {0};
    if (!GetRootPath(root, sizeof(root))) return false;
    char path[MAX_PATH] = {0};
    lstrcpynA(path, root, sizeof(path));
    lstrcatA(path, "\\NOLF2_CN\\NOLF2CN_STRINGS.bin");
    HANDLE h = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) { DebugLine("strings .bin not found"); return false; }
    DWORD size = GetFileSize(h, NULL);
    if (size == INVALID_FILE_SIZE || size < 12) { CloseHandle(h); return false; }
    g_dict_buf = (uint8_t*)HeapAlloc(GetProcessHeap(), 0, size + 1);
    if (!g_dict_buf) { CloseHandle(h); return false; }
    DWORD got = 0;
    BOOL ok = ReadFile(h, g_dict_buf, size, &got, NULL);
    CloseHandle(h);
    if (!ok || got < size || memcmp(g_dict_buf, "CNS2", 4) != 0) return false;
    g_main_count = *(uint32_t*)(g_dict_buf + 4);
    g_fmt_count  = *(uint32_t*)(g_dict_buf + 8);
    int mc = g_main_count, fc = g_fmt_count;
    g_den     = (const char**)HeapAlloc(GetProcessHeap(), 0, sizeof(char*) * (mc + 1));
    g_den_len = (int*)HeapAlloc(GetProcessHeap(), 0, sizeof(int) * (mc + 1));
    g_dm      = (int*)HeapAlloc(GetProcessHeap(), 0, sizeof(int) * (mc + 1));
    g_dcps    = (const uint32_t**)HeapAlloc(GetProcessHeap(), 0, sizeof(uint32_t*) * (mc + 1));
    g_fen     = (const char**)HeapAlloc(GetProcessHeap(), 0, sizeof(char*) * (fc + 1));
    g_fen_len = (int*)HeapAlloc(GetProcessHeap(), 0, sizeof(int) * (fc + 1));
    g_fm      = (int*)HeapAlloc(GetProcessHeap(), 0, sizeof(int) * (fc + 1));
    g_fcps    = (const uint32_t**)HeapAlloc(GetProcessHeap(), 0, sizeof(uint32_t*) * (fc + 1));
    if (!g_den || !g_den_len || !g_dm || !g_dcps || !g_fen || !g_fen_len || !g_fm || !g_fcps) { g_main_count = 0; return false; }
    uint8_t* p = g_dict_buf + 12;
    uint8_t* endp = g_dict_buf + size;
    for (int i = 0; i < mc; ++i) {
        if (p + 2 > endp) { g_main_count = i; break; }
        int el = *(uint16_t*)p; p += 2;
        if (p + el + 2 > endp) { g_main_count = i; break; }
        g_den[i] = (const char*)p; g_den_len[i] = el; p += el;
        int m = *(uint16_t*)p; p += 2;
        if (p + m * 4 > endp) { g_main_count = i; break; }
        g_dm[i] = m; g_dcps[i] = (const uint32_t*)p; p += m * 4;
    }
    for (int i = 0; i < fc; ++i) {
        if (p + 2 > endp) { g_fmt_count = i; break; }
        int el = *(uint16_t*)p; p += 2;
        if (p + el + 2 > endp) { g_fmt_count = i; break; }
        g_fen[i] = (const char*)p; g_fen_len[i] = el; p += el;
        int m = *(uint16_t*)p; p += 2;
        if (p + m * 4 > endp) { g_fmt_count = i; break; }
        g_fm[i] = m; g_fcps[i] = (const uint32_t*)p; p += m * 4;
    }
    char msg[80]; sprintf_s(msg, sizeof(msg), "dict loaded: %d main + %d fmt", g_main_count, g_fmt_count);
    DebugLine(msg);
    return g_main_count > 0;
}

static int DictCmp(const char* en, int el, const char* text)
{
    for (int i = 0; i < el; ++i) {
        unsigned char b = (unsigned char)text[i];
        if (b == 0) return 1;
        unsigned char a = (unsigned char)en[i];
        if (a != b) return (int)a - (int)b;
    }
    return text[el] == 0 ? 0 : -1;
}

static int LookupCn(const char* text)
{
    if (!text || !g_main_count) return -1;
    int lo = 0, hi = g_main_count - 1;
    while (lo <= hi) {
        int mid = (lo + hi) / 2;
        int c = DictCmp(g_den[mid], g_den_len[mid], text);
        if (c == 0) return mid;
        if (c < 0) lo = mid + 1; else hi = mid - 1;
    }
    return -1;
}

static int DictCmpN(const char* en, int el, const char* text, int tlen)
{
    int n = el < tlen ? el : tlen;
    for (int i = 0; i < n; ++i) {
        unsigned char a = (unsigned char)en[i], b = (unsigned char)text[i];
        if (a != b) return (int)a - (int)b;
    }
    return el - tlen;
}

static int LookupCnN(const char* text, int tlen)
{
    if (!g_main_count) return -1;
    int lo = 0, hi = g_main_count - 1;
    while (lo <= hi) {
        int mid = (lo + hi) / 2;
        int c = DictCmpN(g_den[mid], g_den_len[mid], text, tlen);
        if (c == 0) return mid;
        if (c < 0) lo = mid + 1; else hi = mid - 1;
    }
    return -1;
}

static const char* kFlagChars = "0123456789.+-# lhL";

static bool SpecIsNumeric(char t) { return t=='d'||t=='i'||t=='u'||t=='x'||t=='X'||t=='o'; }
static bool IsNumericCap(const char* p, int len)
{
    if (len <= 0) return false;
    int i = 0; if (p[0]=='-'||p[0]=='+') { i=1; if (len==1) return false; }
    for (; i < len; ++i) { char c=p[i]; if (c<'0'||c>'9') return false; }
    return true;
}

static int SpecLenB(const char* s, int slen, int i, int* argnum, int* isPct, char* typ)
{
    *argnum = 0; *isPct = 0; *typ = 0;
    if (i + 1 < slen && s[i + 1] == '%') { *isPct = 1; return 2; }
    int j = i + 1;
    if (j < slen && s[j] >= '0' && s[j] <= '9') {
        int k = j; while (k < slen && s[k] >= '0' && s[k] <= '9') k++;
        if (k < slen && s[k] == '!') {
            int a = 0; for (int t = j; t < k; ++t) a = a * 10 + (s[t] - '0'); *argnum = a;
            k++; int ss = k; while (k < slen && s[k] != '!') k++;
            if (k > ss) *typ = s[k - 1];
            if (k < slen && s[k] == '!') k++;
            return k - i;
        }
    }
    int k = j; while (k < slen && strchr(kFlagChars, s[k]) && s[k] != 0) k++;
    if (k < slen) { *typ = s[k]; k++; }
    return k - i;
}

static int SpecLenCp(const uint32_t* s, int slen, int i, int* argnum, int* isPct)
{
    *argnum = 0; *isPct = 0;
    if (i + 1 < slen && s[i + 1] == (uint32_t)'%') { *isPct = 1; return 2; }
    int j = i + 1;
    if (j < slen && s[j] >= '0' && s[j] <= '9') {
        int k = j; while (k < slen && s[k] >= '0' && s[k] <= '9') k++;
        if (k < slen && s[k] == (uint32_t)'!') {
            int a = 0; for (int t = j; t < k; ++t) a = a * 10 + (int)(s[t] - '0'); *argnum = a;
            k++; while (k < slen && s[k] != (uint32_t)'!') k++;
            if (k < slen && s[k] == (uint32_t)'!') k++;
            return k - i;
        }
    }
    int k = j; while (k < slen && s[k] < 128 && strchr(kFlagChars, (char)s[k])) k++;
    if (k < slen) k++;
    return k - i;
}

// Match `text` against english template (en,el); if it fits, substitute the captured
// values into the Chinese template (zh,zm) and write codepoints to out. Returns count.
static int MatchAndSub(const char* en, int el, const uint32_t* zh, int zm,
                       const char* text, uint32_t* out, int outcap)
{
    char seg[9][256]; int seglen[9]; int nseg = 1; seglen[0] = 0;
    int specarg[8]; char spectype[8]; int nspec = 0;
    int i = 0, seq = 0;
    while (i < el) {
        if (en[i] == '%') {
            int arg, isp; char typ; int L = SpecLenB(en, el, i, &arg, &isp, &typ);
            if (isp) { if (seglen[nseg - 1] < 255) seg[nseg - 1][seglen[nseg - 1]++] = '%'; i += L; continue; }
            if (nspec >= 8 || nseg >= 9) return 0;
            seq++; int a = arg ? arg : seq; if (a < 1 || a > 8) a = seq;
            spectype[nspec] = typ; specarg[nspec] = a; nspec++;
            nseg++; seglen[nseg - 1] = 0;
            i += L;
        } else {
            if (seglen[nseg - 1] < 255) seg[nseg - 1][seglen[nseg - 1]++] = en[i];
            i++;
        }
    }
    if (nspec == 0) return 0;
    int tlen = (int)strlen(text);
    if (tlen < seglen[0] || memcmp(text, seg[0], seglen[0]) != 0) return 0;
    int ti = seglen[0];
    const char* capp[9]; int capl[9];
    for (int q = 0; q < 9; ++q) { capp[q] = 0; capl[q] = 0; }
    for (int j = 1; j < nseg; ++j) {
        int arg = specarg[j - 1];
        if (seglen[j] == 0) {
            if (j == nseg - 1) { capp[arg] = text + ti; capl[arg] = tlen - ti; ti = tlen;
                if (SpecIsNumeric(spectype[j-1]) && !IsNumericCap(capp[arg], capl[arg])) return 0; break; }
            return 0;
        }
        const char* found = NULL;
        for (const char* pp = text + ti; *pp; ++pp) {
            if ((int)(text + tlen - pp) < seglen[j]) break;
            if (memcmp(pp, seg[j], seglen[j]) == 0) { found = pp; break; }
        }
        if (!found) return 0;
        capp[arg] = text + ti; capl[arg] = (int)(found - (text + ti));
        ti = (int)(found - text) + seglen[j];
        if (SpecIsNumeric(spectype[j-1]) && !IsNumericCap(capp[arg], capl[arg])) return 0;
    }
    if (ti != tlen) return 0;
    int oi = 0; i = 0; seq = 0;
    while (i < zm && oi < outcap - 1) {
        if (zh[i] == (uint32_t)'%') {
            int arg, isp; int L = SpecLenCp(zh, zm, i, &arg, &isp);
            if (isp) { out[oi++] = '%'; i += L; continue; }
            seq++; int a = arg ? arg : seq; if (a < 1 || a > 8) a = seq;
            if (a >= 0 && a < 9 && capp[a]) {
                int tix = LookupCnN(capp[a], capl[a]);  // translate embedded names
                if (tix >= 0) {
                    for (int t = 0; t < g_dm[tix] && oi < outcap - 1; ++t) out[oi++] = g_dcps[tix][t];
                } else {
                    for (int t = 0; t < capl[a] && oi < outcap - 1; ++t)
                        out[oi++] = (uint32_t)(unsigned char)capp[a][t];
                }
            }
            i += L;
        } else {
            out[oi++] = zh[i++];
        }
    }
    return oi;
}

static void EnsureAtlas()
{
    if (g_atlas_tried) return;
    g_atlas_tried = true;
    LoadMetrics();
    LoadDict();
    void* tex = TexIface();
    if (!tex) { DebugLine("TexInterface null"); return; }
    void** vt = *(void***)tex;
    TexCreateFromNameFn create = (TexCreateFromNameFn)vt[VT_CreateTexName];
    void* h = NULL;
    int rc = create(tex, &h, "Interface\\Fonts\\NOLF2CN_ATLAS.DTX");
    if (rc != 0 || !h) {
        char m[64]; sprintf_s(m, sizeof(m), "CreateTextureFromName rc=%d h=%p", rc, h);
        DebugLine(m);
        return;
    }
    g_atlas_tex = h;
    DebugLine("atlas texture created");
}

static int CnDoRender(void* self, RenderFn orig, int start, int end)
{
    EnsureAtlas();
    void** svt = *(void***)self;
    if (!g_atlas_tex || !g_glyph_count || !g_main_count)
        return orig ? orig(self, start, end) : 0;

    const char* text = ((GetTextFn)svt[VP_GetText])(self);
    if (!text || !text[0]) return orig ? orig(self, start, end) : 0;

    const uint32_t* cps; int m;
    uint32_t fbuf[512];
    int idx = LookupCn(text);
    if (idx >= 0) { cps = g_dcps[idx]; m = g_dm[idx]; }
    else {
        int done = 0;
        // objectives etc. are shown as "<base> (optional)"; both halves are in the dict.
        static const char kOpt[] = " (optional)";
        int optlen = (int)(sizeof(kOpt) - 1);
        int tl = (int)strlen(text);
        if (tl > optlen && memcmp(text + tl - optlen, kOpt, optlen) == 0) {
            int bidx = LookupCnN(text, tl - optlen);
            int oidx = LookupCn(kOpt);
            if (bidx >= 0 && oidx >= 0) {
                int mm = 0;
                for (int t = 0; t < g_dm[bidx] && mm < 510; ++t) fbuf[mm++] = g_dcps[bidx][t];
                for (int t = 0; t < g_dm[oidx] && mm < 510; ++t) fbuf[mm++] = g_dcps[oidx][t];
                cps = fbuf; m = mm; done = 1;
            }
        }
        // item pickups are shown as "<name>!"; the name is in the dict.
        if (!done && tl > 1 && text[tl - 1] == '!') {
            int bidx = LookupCnN(text, tl - 1);
            if (bidx >= 0) {
                int mm = 0;
                for (int t = 0; t < g_dm[bidx] && mm < 510; ++t) fbuf[mm++] = g_dcps[bidx][t];
                if (mm < 510) fbuf[mm++] = '!';
                cps = fbuf; m = mm; done = 1;
            }
        }
        // "Select <item>" and "Select <item> : n/m"
        if (!done) {
            static const char kSel[] = "Select ";
            int sl = (int)(sizeof(kSel) - 1);
            if (tl > sl && memcmp(text, kSel, sl) == 0) {
                const char* rem = text + sl; int remlen = tl - sl;
                int sidx = LookupCn("Select");
                int bidx = LookupCnN(rem, remlen);
                if (bidx >= 0 && sidx >= 0) {
                    int mm = 0;
                    for (int t = 0; t < g_dm[sidx] && mm < 510; ++t) fbuf[mm++] = g_dcps[sidx][t];
                    for (int t = 0; t < g_dm[bidx] && mm < 510; ++t) fbuf[mm++] = g_dcps[bidx][t];
                    cps = fbuf; m = mm; done = 1;
                } else if (sidx >= 0) {
                    const char* colon = NULL;
                    for (int q = 0; q + 3 <= remlen; ++q)
                        if (rem[q] == ' ' && rem[q+1] == ':' && rem[q+2] == ' ') { colon = rem + q; break; }
                    if (colon) {
                        int nidx = LookupCnN(rem, (int)(colon - rem));
                        if (nidx >= 0) {
                            int mm = 0;
                            for (int t = 0; t < g_dm[sidx] && mm < 510; ++t) fbuf[mm++] = g_dcps[sidx][t];
                            for (int t = 0; t < g_dm[nidx] && mm < 510; ++t) fbuf[mm++] = g_dcps[nidx][t];
                            for (const char* pp = colon; *pp && mm < 510; ++pp) fbuf[mm++] = (uint32_t)(unsigned char)*pp;
                            cps = fbuf; m = mm; done = 1;
                        }
                    }
                }
            }
        }
        // weapon HUD ammo shown as "(cur/max) <name>"; translate the trailing name.
        if (!done && text[0] == '(') {
            const char* rp = NULL;
            for (const char* q = text; q[0] && q[1]; ++q)
                if (q[0] == ')' && q[1] == ' ') { rp = q; break; }
            if (rp) {
                const char* name = rp + 2;
                int nlen = tl - (int)(name - text);
                int nidx = (nlen > 0) ? LookupCnN(name, nlen) : -1;
                if (nidx >= 0) {
                    int mm = 0;
                    int prefixlen = (int)(name - text);
                    for (int t = 0; t < prefixlen && mm < 510; ++t) fbuf[mm++] = (uint32_t)(unsigned char)text[t];
                    for (int t = 0; t < g_dm[nidx] && mm < 510; ++t) fbuf[mm++] = g_dcps[nidx][t];
                    cps = fbuf; m = mm; done = 1;
                }
            }
        }
        if (!done) {
            int fm = 0;
            for (int fi = 0; fi < g_fmt_count; ++fi) {
                fm = MatchAndSub(g_fen[fi], g_fen_len[fi], g_fcps[fi], g_fm[fi], text, fbuf, 512);
                if (fm > 0) break;
            }
            if (fm <= 0) {
                if ((int)strlen(text) > 80) {
                    static int dbgn = 0;
                    if (dbgn < 40) { dbgn++; char mb[80]; sprintf_s(mb, sizeof(mb), "unmatched: %.60s", text); DebugLine(mb); }
                }
                return orig ? orig(self, start, end) : 0;
            }
            cps = fbuf; m = fm;
        }
    }

    LT_POLYGT4* polys = (LT_POLYGT4*)((GetPolysFn)svt[VP_GetPolys])(self);
    int n = (int)((GetLenFn)svt[VP_GetLength])(self);
    void* font = ((GetFontFn)svt[VP_GetFont])(self);
    if (!polys || !font || n <= 0 || n >= 4096)
        return orig ? orig(self, start, end) : 0;

    float x0 = polys[0].verts[0].x;
    float y0 = polys[0].verts[0].y;
    float hgt = polys[0].verts[3].y - polys[0].verts[0].y;
    if (hgt < 4.0f) hgt = 18.0f;
    LT_VERTRGBA col = polys[0].verts[0].rgba;

    float maxRight = x0, minX = x0, minY = polys[0].verts[0].y, maxY = minY;
    for (int i = 0; i < n; ++i) {
        if (polys[i].verts[1].x > maxRight) maxRight = polys[i].verts[1].x;
        if (polys[i].verts[0].x < minX) minX = polys[i].verts[0].x;
        float qy = polys[i].verts[0].y;
        if (qy < minY) minY = qy;
        if (qy > maxY) maxY = qy;
    }
    bool multiline = (maxY - minY) > hgt * 0.5f;
    float lineW = maxRight - x0;
    if (!multiline || lineW < hgt * 2.0f) lineW = 1.0e9f;
    float lineH = hgt * 1.25f;

    // Re-anchor a single line to match the original text's alignment (left/center/
    // right), so centered subtitles stay centered instead of drifting left.
    float startX = minX;
    if (!multiline) {
        float W = 0;
        for (int i = 0; i < m; ++i) {
            uint32_t cp = cps[i];
            if (cp == 0x0A || cp == 0x20) { W += hgt * 0.5f; continue; }
            int gi = LookupGlyph(cp);
            W += (gi >= 0) ? g_adv[gi] * hgt : hgt * 0.5f;
        }
        float px = minX, py = 0;
        ((GetPosFn)svt[VP_GetPosition])(self, &px, &py);
        float EW = maxRight - minX;
        float f = (EW > 1.0f) ? (px - minX) / EW : 0.0f;
        if (f < 0) f = 0; if (f > 1) f = 1;
        startX = px - f * W;
    }

    float penx = startX, peny = y0;
    int qi = 0;
    for (int i = 0; i < m && qi < n; ++i) {
        uint32_t cp = cps[i];
        if (cp == 0x0A) { penx = startX; peny += lineH; continue; }
        if (cp == 0x20) { penx += hgt * 0.5f; continue; }
        int gi = LookupGlyph(cp);
        if (gi < 0) { penx += hgt * 0.5f; continue; }
        float advn = g_adv[gi];
        float w = advn * hgt;
        if (penx + w > startX + lineW + 0.5f && penx > startX) { penx = startX; peny += lineH; }
        float u0 = g_u0[gi], v0 = g_v0[gi], v1 = g_v1[gi];
        float u1 = u0 + advn * (g_u1[gi] - g_u0[gi]);
        LT_POLYGT4* q = &polys[qi++];
        q->verts[0].x=penx;   q->verts[0].y=peny;      q->verts[0].u=u0; q->verts[0].v=v0; q->verts[0].rgba=col;
        q->verts[1].x=penx+w; q->verts[1].y=peny;      q->verts[1].u=u1; q->verts[1].v=v0; q->verts[1].rgba=col;
        q->verts[2].x=penx+w; q->verts[2].y=peny+hgt;  q->verts[2].u=u1; q->verts[2].v=v1; q->verts[2].rgba=col;
        q->verts[3].x=penx;   q->verts[3].y=peny+hgt;  q->verts[3].u=u0; q->verts[3].v=v1; q->verts[3].rgba=col;
        penx += w;
    }
    for (int i = qi; i < n; ++i)
        for (int v = 0; v < 4; ++v) polys[i].verts[v].rgba.a = 0;

    void** fvt = *(void***)font;
    void* origTex = ((FontGetTexFn)fvt[VF_GetTexture])(font);
    ((FontSetTexFn)fvt[VF_SetTexture])(font, g_atlas_tex, (void*)0, (unsigned char)0);
    int rc = orig ? orig(self, start, end) : 0;
    ((FontSetTexFn)fvt[VF_SetTexture])(font, origTex, (void*)0, (unsigned char)0);
    return rc;
}

extern "C" int __fastcall CnRenderHookFmt(void* self, void* /*edx*/, int start, int end)
{ return CnDoRender(self, g_orig_render_fmt, start, end); }
extern "C" int __fastcall CnRenderHookPlain(void* self, void* /*edx*/, int start, int end)
{ return CnDoRender(self, g_orig_render_plain, start, end); }

static void PatchRender(void* poly, bool plain)
{
    if (!poly) return;
    if (plain ? g_plain_patched : g_fmt_patched) return;
    void** vt = *(void***)poly;
    if (!vt) return;
    RenderFn orig = (RenderFn)vt[VP_Render];
    void* hook = plain ? (void*)&CnRenderHookPlain : (void*)&CnRenderHookFmt;
    DWORD old = 0;
    if (!VirtualProtect(&vt[VP_Render], sizeof(void*), PAGE_EXECUTE_READWRITE, &old)) return;
    vt[VP_Render] = hook;
    DWORD restore = 0;
    VirtualProtect(&vt[VP_Render], sizeof(void*), old, &restore);
    FlushInstructionCache(GetCurrentProcess(), &vt[VP_Render], sizeof(void*));
    if (plain) { g_orig_render_plain = orig; g_plain_patched = true; DebugLine("patched plain CUIPolyString::Render"); }
    else       { g_orig_render_fmt = orig;   g_fmt_patched = true;   DebugLine("patched formatted CUIPolyString::Render"); }
}

extern "C" void* __fastcall CnCreateFormattedHook(void* self, void* /*edx*/, void* font, char* buffer, float x, float y, int alignment)
{
    void* poly = g_orig_create_formatted(self, font, buffer, x, y, alignment);
    if (poly) PatchRender(poly, false);
    return poly;
}

extern "C" void* __fastcall CnCreatePolyHook(void* self, void* /*edx*/, void* font, char* buffer, float x, float y)
{
    void* poly = g_orig_create_polystr(self, font, buffer, x, y);
    if (font) PatchFontDrawString(font);
    if (poly) PatchRender(poly, true);
    return poly;
}

static void TryPatchFontManager()
{
    if (g_fontmgr_patched || !g_original) return;
    void* mgr = *(void**)(Base() + kFontMgrGlobalRva);
    if (!mgr) return;
    void** vt = *(void***)mgr;
    if (!vt) return;
    if (!g_orig_create_formatted) g_orig_create_formatted = (CreateFormattedFn)vt[VF_CreateFormatted];
    DWORD old = 0;
    if (VirtualProtect(&vt[VF_CreateFormatted], sizeof(void*), PAGE_EXECUTE_READWRITE, &old)) {
        vt[VF_CreateFormatted] = (void*)&CnCreateFormattedHook;
        DWORD restore = 0; VirtualProtect(&vt[VF_CreateFormatted], sizeof(void*), old, &restore);
        FlushInstructionCache(GetCurrentProcess(), &vt[VF_CreateFormatted], sizeof(void*));
    }
    // NOTE (2026-07-13): the CreatePolyString (plain) hook was REMOVED. Hooking it crashed
    // the game right after a level load completes ("Continue" -> load -> crash). We revert
    // to the documented-stable config: hook ONLY CreateFormattedPolyString + its Render.
    // (Cost: the one scrolling long-help string, id 11016, stays English. Acceptable.)
    g_fontmgr_patched = true;
    DebugLine("patched CreateFormattedPolyString (formatted-only stable)");
}

extern "C" void __fastcall CnDrawStringHook(void* font, void* /*edx*/, float x, float y, char* text)
{
    if (text && text[0]) {
        static int dbgn = 0;
        if (dbgn < 60) { dbgn++; char mb[96]; sprintf_s(mb, sizeof(mb), "DrawString: %.70s", text); DebugLine(mb); }
    }
    if (g_orig_drawstring) g_orig_drawstring(font, x, y, text);
}

static void PatchFontDrawString(void* font)
{
    if (g_ds_patched || !font) return;
    void** vt = *(void***)font;
    if (!vt) return;
    g_orig_drawstring = (DrawStringFn)vt[VF_DrawString];
    DWORD old = 0;
    if (!VirtualProtect(&vt[VF_DrawString], sizeof(void*), PAGE_EXECUTE_READWRITE, &old)) return;
    vt[VF_DrawString] = (void*)&CnDrawStringHook;
    DWORD restore = 0;
    VirtualProtect(&vt[VF_DrawString], sizeof(void*), old, &restore);
    FlushInstructionCache(GetCurrentProcess(), &vt[VF_DrawString], sizeof(void*));
    g_ds_patched = true;
    DebugLine("patched CUIFont::DrawString");
}

static bool EnsureOriginal()
{
    if (g_original) return true;
    char root[MAX_PATH] = {0};
    if (!GetRootPath(root, sizeof(root))) { DebugLine("no game root"); return false; }
    char path[MAX_PATH] = {0};
    lstrcpynA(path, root, sizeof(path));
    lstrcatA(path, "\\NOLF2_CN\\CSHELL_MODERNIZER_ORIG.DLL");
    g_original = LoadLibraryA(path);
    if (!g_original) { DebugLine("failed to load CSHELL_MODERNIZER_ORIG.DLL"); return false; }
    g_set_master_database = (SetMasterDatabaseFn)GetProcAddress(g_original, "SetMasterDatabase");
    if (!g_set_master_database) { DebugLine("no SetMasterDatabase export"); return false; }
    return true;
}

extern "C" __declspec(dllexport) void __cdecl SetMasterDatabase(void* master_database)
{
    if (EnsureOriginal() && g_set_master_database) {
        g_set_master_database(master_database);
        TryPatchFontManager();
    }
}

BOOL APIENTRY DllMain(HMODULE module, DWORD reason, LPVOID)
{
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(module);
        DebugLine("renderer proxy attached");
    }
    return TRUE;
}
