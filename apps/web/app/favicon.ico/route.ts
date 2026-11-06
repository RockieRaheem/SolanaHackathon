import { NextResponse } from 'next/server';

export function GET(request: Request) {
  return NextResponse.redirect(new URL('/harambeeone-logo.png', request.url));
}
