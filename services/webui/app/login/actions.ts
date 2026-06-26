"use server";

import { AuthError } from "next-auth";
import { redirect } from "next/navigation";
import { signIn } from "@/auth";

export async function login(formData: FormData) {
  try {
    await signIn("credentials", {
      username: formData.get("username"),
      password: formData.get("password"),
      redirectTo: "/",
    });
  } catch (error) {
    // signIn lève un redirect (NEXT_REDIRECT) en cas de succès → on le relaie.
    if (error instanceof AuthError) {
      redirect("/login?error=1");
    }
    throw error;
  }
}
