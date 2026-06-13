"use client";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-gray-950 text-white flex flex-col items-center justify-center gap-4 p-6">
        <h2 className="text-lg font-semibold">Something went wrong</h2>
        <p className="text-sm text-gray-400 max-w-md text-center">
          {error.message || "An unexpected error occurred."}
        </p>
        <button
          onClick={() => reset()}
          className="bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg text-sm"
        >
          Try again
        </button>
      </body>
    </html>
  );
}
