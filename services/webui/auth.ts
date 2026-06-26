import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import bcrypt from "bcryptjs";

// Auth mono-utilisateur (ADR 0005, CGU usage perso) : un seul compte, identifiants en
// variables d'env (mot de passe haché bcrypt). Aucune base, aucun provider tiers.
const WEBUI_USER = process.env.WEBUI_USER ?? "admin";
const WEBUI_PASSWORD_HASH = process.env.WEBUI_PASSWORD_HASH ?? "";

export const { handlers, auth, signIn, signOut } = NextAuth({
  trustHost: true, // local / docker (pas derrière un proxy Vercel)
  session: { strategy: "jwt" },
  pages: { signIn: "/login" },
  providers: [
    Credentials({
      credentials: { username: {}, password: {} },
      authorize: async (creds) => {
        const username = String(creds?.username ?? "");
        const password = String(creds?.password ?? "");
        if (!WEBUI_PASSWORD_HASH || username !== WEBUI_USER) return null;
        const ok = await bcrypt.compare(password, WEBUI_PASSWORD_HASH);
        return ok ? { id: "webui-user", name: WEBUI_USER } : null;
      },
    }),
  ],
});
