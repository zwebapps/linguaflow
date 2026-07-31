import { z } from "zod";

export const emailSchema = z.string().email("Enter a valid email");
export const passwordSchema = z.string().min(8, "Password must be at least 8 characters");
export const chatMessageSchema = z
  .string()
  .trim()
  .min(1, "Message cannot be empty")
  .max(4000, "Message must be at most 4000 characters");
export const writingTextSchema = z
  .string()
  .trim()
  .min(1, "Text cannot be empty")
  .max(5000, "Text must be at most 5000 characters");
export const cefrSchema = z.enum(["A1", "A2", "B1", "B2", "C1"]);
export const quizCountSchema = z.coerce.number().int().min(1).max(20);

export const loginSchema = z.object({
  email: emailSchema,
  password: z.string().min(1, "Password is required"),
});

export const registerSchema = z.object({
  email: emailSchema,
  password: passwordSchema,
  display_name: z.string().trim().min(1, "Display name is required").max(64),
});

export const onboardingSchema = z.object({
  goal: z.enum(["travel", "work", "study", "heritage", "exam"]),
  cefr_level: cefrSchema,
  learning_style: z.enum(["visual", "balanced", "conversation"]),
  daily_goal_minutes: z.coerce.number().int().min(5).max(120),
});
